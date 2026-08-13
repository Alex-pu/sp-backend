from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from auth_utils import is_owner, resolve_accessible_shop
from models import Expense, Shift, db
from datetime import datetime

expenses_bp = Blueprint('expenses', __name__, url_prefix='/api/expenses')


@expenses_bp.route('', methods=['POST'])
@jwt_required()
def sync_expense():
    """Receive a synced expense from Flutter.  Idempotent on expense id."""
    user_id = get_jwt_identity()
    claims = get_jwt()
    owner = is_owner()
    data = request.get_json() or {}

    if not data.get('category') or 'amount' not in data:
        return jsonify({'success': False, 'message': 'category and amount are required'}), 400

    # Idempotency
    if data.get('id'):
        existing = Expense.query.get(data['id'])
        if existing:
            return jsonify({'success': True, 'message': 'Already synced', 'data': existing.to_dict()}), 200

    try:
        shop = resolve_accessible_shop(data.get('shopId') or claims.get('shopId'))
        shop_id = shop.id
        cashier_id = data.get('cashierId', user_id) if owner else user_id
        cashier_name = data.get('cashierName', claims.get('name', '')) if owner else claims.get('name', '')

        shift_id = data.get('shiftId')
        if not shift_id and not owner:
            open_shift = Shift.query.filter_by(
                cashier_id=user_id,
                shop_id=shop_id,
                status='open',
            ).first()
            if not open_shift:
                return jsonify({'success': False, 'message': 'An open shift is required before recording expenses'}), 400
            shift_id = open_shift.id

        if shift_id:
            shift = Shift.query.get(shift_id)
            if not shift:
                return jsonify({'success': False, 'message': 'Shift not found'}), 400
            if shift.status != 'open':
                return jsonify({'success': False, 'message': 'Shift must be open'}), 400
            if shift.shop_id and shift.shop_id != shop_id:
                return jsonify({'success': False, 'message': 'Shift does not belong to this shop'}), 400
            if not owner and shift.cashier_id != user_id:
                return jsonify({'success': False, 'message': 'Shift does not belong to this cashier'}), 400

        expense = Expense(
            id=data.get('id'),   # None → auto-generated UUID
            shift_id=shift_id,
            shop_id=shop_id,
            cashier_id=cashier_id,
            cashier_name=cashier_name,

            category=data['category'],
            amount=float(data['amount']),
            description=data.get('description', ''),
            payment_method=data.get('paymentMethod', 'cash'),
            approval_status=data.get('approvalStatus', 'pending'),
            created_at=(
                datetime.fromisoformat(data['createdAt'])
                if data.get('createdAt') else datetime.utcnow()
            ),
        )
        db.session.add(expense)
        db.session.commit()
        return jsonify({'success': True, 'data': expense.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@expenses_bp.route('', methods=['GET'])
@jwt_required()
def list_expenses():
    """List expenses.  Owner sees all; cashier sees only their own."""
    user_id = get_jwt_identity()
    claims = get_jwt()

    query = Expense.query
    if claims.get('role') != 'owner':
        query = query.filter_by(cashier_id=user_id)

    shift_id = request.args.get('shiftId')
    shop_id = request.args.get('shopId')
    status = request.args.get('status')
    if shift_id:
        query = query.filter_by(shift_id=shift_id)
    if shop_id and is_owner():
        query = query.filter_by(shop_id=shop_id)
    if status:
        query = query.filter_by(approval_status=status)

    expenses = query.order_by(Expense.created_at.desc()).limit(200).all()
    return jsonify({'success': True, 'data': [e.to_dict() for e in expenses]}), 200


@expenses_bp.route('/<expense_id>/approve', methods=['PUT'])
@jwt_required()
def approve_expense(expense_id):
    claims = get_jwt()
    if not is_owner():
        return jsonify({'success': False, 'message': 'Owner access required'}), 403

    expense = Expense.query.get(expense_id)
    if not expense:
        return jsonify({'success': False, 'message': 'Expense not found'}), 404

    expense.approval_status = 'approved'
    expense.approved_by = claims.get('name', '')
    db.session.commit()
    return jsonify({'success': True, 'data': expense.to_dict()}), 200


@expenses_bp.route('/<expense_id>/reject', methods=['PUT'])
@jwt_required()
def reject_expense(expense_id):
    claims = get_jwt()
    if not is_owner():
        return jsonify({'success': False, 'message': 'Owner access required'}), 403

    expense = Expense.query.get(expense_id)
    if not expense:
        return jsonify({'success': False, 'message': 'Expense not found'}), 404

    expense.approval_status = 'rejected'
    expense.approved_by = claims.get('name', '')
    db.session.commit()
    return jsonify({'success': True, 'data': expense.to_dict()}), 200
