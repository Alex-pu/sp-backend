from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from auth_utils import is_owner, resolve_accessible_shop
from models import Shift, Transaction, Payment, Expense, User, db
from datetime import datetime

shifts_bp = Blueprint('shifts', __name__, url_prefix='/api/shifts')


@shifts_bp.route('', methods=['POST'])
@jwt_required()
def open_shift():
    """Open a new shift.  A cashier can only have one open shift at a time."""
    user_id = get_jwt_identity()
    claims = get_jwt()
    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404

    existing = Shift.query.filter_by(cashier_id=user_id, status='open').first()
    if existing:
        return jsonify({
            'success': False,
            'message': 'You already have an open shift',
            'data': existing.to_dict()
        }), 409

    data = request.get_json() or {}
    opening_float = float(data.get('openingFloat', 0))
    try:
        shop = resolve_accessible_shop(data.get('shopId'))
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    shift = Shift(
        cashier_id=user_id,
        shop_id=shop.id,
        cashier_name=claims.get('name', ''),

        opening_float=opening_float,
    )
    db.session.add(shift)
    db.session.commit()

    return jsonify({'success': True, 'data': shift.to_dict()}), 201


@shifts_bp.route('', methods=['GET'])
@jwt_required()
def list_shifts():
    """List shifts.  Owner sees all; cashier sees only their own."""
    user_id = get_jwt_identity()
    claims = get_jwt()

    query = Shift.query
    if not is_owner():
        query = query.filter_by(cashier_id=user_id)

    status = request.args.get('status')
    shop_id = request.args.get('shopId')
    if status:
        query = query.filter_by(status=status)
    if shop_id and is_owner():
        try:
            shop = resolve_accessible_shop(shop_id)
            query = query.filter_by(shop_id=shop.id)
        except ValueError as e:
            return jsonify({'success': False, 'message': str(e)}), 400

    shifts = query.order_by(Shift.opened_at.desc()).limit(100).all()
    return jsonify({'success': True, 'data': [s.to_dict() for s in shifts]}), 200


@shifts_bp.route('/current', methods=['GET'])
@jwt_required()
def current_shift():
    """Return the cashier's currently open shift, if any."""
    user_id = get_jwt_identity()
    shift = Shift.query.filter_by(cashier_id=user_id, status='open').first()
    if not shift:
        return jsonify({'success': False, 'message': 'No open shift'}), 404
    return jsonify({'success': True, 'data': shift.to_dict()}), 200


@shifts_bp.route('/<shift_id>', methods=['GET'])
@jwt_required()
def get_shift(shift_id):
    user_id = get_jwt_identity()
    claims = get_jwt()
    shift = Shift.query.get(shift_id)
    if not shift:
        return jsonify({'success': False, 'message': 'Shift not found'}), 404
    if not is_owner() and shift.cashier_id != user_id:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    return jsonify({'success': True, 'data': shift.to_dict()}), 200


@shifts_bp.route('/<shift_id>/close', methods=['PUT'])
@jwt_required()
def close_shift(shift_id):
    """Close a shift with the actual cash count; calculates variance automatically."""
    user_id = get_jwt_identity()
    claims = get_jwt()
    shift = Shift.query.get(shift_id)

    if not shift:
        return jsonify({'success': False, 'message': 'Shift not found'}), 404
    if shift.status == 'closed':
        return jsonify({'success': False, 'message': 'Shift is already closed'}), 400
    if not is_owner() and shift.cashier_id != user_id:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    data = request.get_json() or {}
    closing_cash = float(data.get('closingCash', 0))

    # Sum cash payments from the payments table (handles split-bill correctly)
    cash_sales = db.session.query(db.func.sum(Payment.amount)).join(
        Transaction, Payment.transaction_id == Transaction.id
    ).filter(
        Transaction.shift_id == shift_id,
        Transaction.status == 'completed',
        Payment.method == 'cash',
    ).scalar() or 0.0

    # Only approved cash expenses reduce expected float
    cash_expenses = db.session.query(db.func.sum(Expense.amount)).filter(
        Expense.shift_id == shift_id,
        Expense.payment_method == 'cash',
        Expense.approval_status == 'approved',
    ).scalar() or 0.0

    expected_cash = shift.opening_float + cash_sales - cash_expenses

    shift.closing_cash = closing_cash
    shift.expected_cash = round(expected_cash, 2)
    shift.variance = round(closing_cash - expected_cash, 2)
    shift.notes = data.get('notes', '')
    shift.status = 'closed'
    shift.closed_at = datetime.utcnow()
    db.session.commit()

    return jsonify({'success': True, 'data': shift.to_dict()}), 200


@shifts_bp.route('/<shift_id>/summary', methods=['GET'])
@jwt_required()
def shift_summary(shift_id):
    """Full summary: transaction count, revenue by method, expenses."""
    user_id = get_jwt_identity()
    claims = get_jwt()
    shift = Shift.query.get(shift_id)

    if not shift:
        return jsonify({'success': False, 'message': 'Shift not found'}), 404
    if not is_owner() and shift.cashier_id != user_id:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    transactions = Transaction.query.filter_by(
        shift_id=shift_id, status='completed'
    ).all()
    expenses = Expense.query.filter_by(shift_id=shift_id).all()

    # Revenue grouped by payment leg (from payments table)
    by_method: dict = {}
    for txn in transactions:
        for pmt in txn.payments:
            by_method[pmt.method] = round(by_method.get(pmt.method, 0.0) + pmt.amount, 2)
    # Fallback for non-split transactions that may not have payment rows
    if not by_method:
        for txn in transactions:
            by_method[txn.payment_method] = round(
                by_method.get(txn.payment_method, 0.0) + txn.grand_total, 2
            )

    total_revenue = sum(t.grand_total for t in transactions)
    total_expenses = sum(e.amount for e in expenses if e.approval_status == 'approved')

    return jsonify({
        'success': True,
        'data': {
            'shift': shift.to_dict(),
            'totalTransactions': len(transactions),
            'totalRevenue': round(total_revenue, 2),
            'revenueByMethod': by_method,
            'totalExpenses': round(total_expenses, 2),
            'netRevenue': round(total_revenue - total_expenses, 2),
            'expenses': [e.to_dict() for e in expenses],
        }
    }), 200
