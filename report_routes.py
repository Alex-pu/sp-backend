from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from auth_utils import is_owner, owner_required_response, resolve_accessible_shop
from models import Transaction, Expense
from datetime import datetime, date, timedelta

reports_bp = Blueprint('reports', __name__, url_prefix='/api/reports')


@reports_bp.route('/daily', methods=['GET'])
@jwt_required()
def daily_report():
    """Sales summary for a single day.  Owner only."""
    owner_error = owner_required_response()
    if owner_error:
        return owner_error

    date_str = request.args.get('date', date.today().isoformat())
    shop_id = request.args.get('shopId')
    shop = None
    if shop_id:
        try:
            shop = resolve_accessible_shop(shop_id)
            shop_id = shop.id
        except ValueError as e:
            return jsonify({'success': False, 'message': str(e)}), 400
    try:
        report_date = datetime.fromisoformat(date_str).date()
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid date format, use YYYY-MM-DD'}), 400

    start = datetime.combine(report_date, datetime.min.time())
    end = datetime.combine(report_date, datetime.max.time())

    transactions = Transaction.query.filter(
        Transaction.created_at.between(start, end),
        Transaction.status == 'completed',
    )
    if shop_id:
        transactions = transactions.filter(Transaction.shop_id == shop_id)
    transactions = transactions.all()

    expenses = Expense.query.filter(
        Expense.created_at.between(start, end),
        Expense.approval_status == 'approved',
    )
    if shop_id:
        expenses = expenses.filter(Expense.shop_id == shop_id)
    expenses = expenses.all()

    total_revenue = sum(t.grand_total for t in transactions)
    total_tax = sum(t.tax_total for t in transactions)
    total_discount = sum(t.discount_total for t in transactions)
    total_expenses = sum(e.amount for e in expenses)

    # Revenue by payment method (from payments legs for accuracy)
    by_method: dict = {}
    for txn in transactions:
        for pmt in txn.payments:
            by_method[pmt.method] = round(by_method.get(pmt.method, 0.0) + pmt.amount, 2)
    if not by_method:
        for txn in transactions:
            by_method[txn.payment_method] = round(
                by_method.get(txn.payment_method, 0.0) + txn.grand_total, 2
            )

    # Revenue by cashier
    by_cashier: dict = {}
    for txn in transactions:
        entry = by_cashier.setdefault(txn.cashier_name, {'count': 0, 'total': 0.0})
        entry['count'] += 1
        entry['total'] = round(entry['total'] + txn.grand_total, 2)

    return jsonify({
        'success': True,
        'data': {
            'date': date_str,
            'shopId': shop_id,
            'shopName': shop.name if shop else None,
            'totalTransactions': len(transactions),
            'totalRevenue': round(total_revenue, 2),
            'totalTax': round(total_tax, 2),
            'totalDiscount': round(total_discount, 2),
            'totalExpenses': round(total_expenses, 2),
            'netRevenue': round(total_revenue - total_expenses, 2),
            'revenueByMethod': by_method,
            'revenueByCashier': by_cashier,
        }
    }), 200


@reports_bp.route('/range', methods=['GET'])
@jwt_required()
def range_report():
    """Sales summary over a date range (default: last 7 days).  Owner only."""
    owner_error = owner_required_response()
    if owner_error:
        return owner_error

    default_from = (date.today() - timedelta(days=6)).isoformat()
    date_from = request.args.get('from', default_from)
    date_to = request.args.get('to', date.today().isoformat())
    shop_id = request.args.get('shopId')
    shop = None
    if shop_id:
        try:
            shop = resolve_accessible_shop(shop_id)
            shop_id = shop.id
        except ValueError as e:
            return jsonify({'success': False, 'message': str(e)}), 400

    try:
        start = datetime.fromisoformat(date_from)
        end = datetime.combine(datetime.fromisoformat(date_to).date(), datetime.max.time())
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid date format, use YYYY-MM-DD'}), 400

    transactions = Transaction.query.filter(
        Transaction.created_at.between(start, end),
        Transaction.status == 'completed',
    )
    if shop_id:
        transactions = transactions.filter(Transaction.shop_id == shop_id)
    transactions = transactions.order_by(Transaction.created_at.desc()).all()

    expenses = Expense.query.filter(
        Expense.created_at.between(start, end),
        Expense.approval_status == 'approved',
    )
    if shop_id:
        expenses = expenses.filter(Expense.shop_id == shop_id)
    expenses = expenses.all()

    # Daily breakdown
    daily: dict = {}
    for txn in transactions:
        day = txn.created_at.date().isoformat()
        entry = daily.setdefault(day, {'transactions': 0, 'revenue': 0.0})
        entry['transactions'] += 1
        entry['revenue'] = round(entry['revenue'] + txn.grand_total, 2)

    return jsonify({
        'success': True,
        'data': {
            'from': date_from,
            'to': date_to,
            'shopId': shop_id,
            'shopName': shop.name if shop else None,
            'totalTransactions': len(transactions),
            'totalRevenue': round(sum(t.grand_total for t in transactions), 2),
            'totalExpenses': round(sum(e.amount for e in expenses), 2),
            'dailyBreakdown': daily,
        }
    }), 200


@reports_bp.route('/cashier/<cashier_id>', methods=['GET'])
@jwt_required()
def cashier_report(cashier_id):
    """All transactions for a specific cashier.  Owner or the cashier themselves."""
    user_id = get_jwt_identity()
    if not is_owner() and user_id != cashier_id:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    date_from = request.args.get('from')
    date_to = request.args.get('to')
    shop_id = request.args.get('shopId')

    query = Transaction.query.filter_by(cashier_id=cashier_id, status='completed')
    if shop_id:
        if not is_owner():
            return jsonify({'success': False, 'message': 'Owner access required for shop filter'}), 403
        try:
            shop = resolve_accessible_shop(shop_id)
            query = query.filter(Transaction.shop_id == shop.id)
        except ValueError as e:
            return jsonify({'success': False, 'message': str(e)}), 400
    if date_from:
        query = query.filter(Transaction.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(
            Transaction.created_at <= datetime.combine(
                datetime.fromisoformat(date_to).date(), datetime.max.time()
            )
        )

    transactions = query.order_by(Transaction.created_at.desc()).all()

    return jsonify({
        'success': True,
        'data': {
            'cashierId': cashier_id,
            'totalTransactions': len(transactions),
            'totalRevenue': round(sum(t.grand_total for t in transactions), 2),
            'transactions': [t.to_dict() for t in transactions],
        }
    }), 200
