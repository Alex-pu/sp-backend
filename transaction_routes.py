from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from auth_utils import is_owner, owner_required_response, resolve_accessible_shop
from models import Transaction, TransactionItem, Payment, Product, Shift, db
from stock_routes import apply_stock_movement
from datetime import datetime

transactions_bp = Blueprint('transactions', __name__, url_prefix='/api/transactions')


def _build_transaction(data, user_id, claims):
    """Create Transaction + children from a dict. Deducts stock. No commit."""
    shop = resolve_accessible_shop(data.get('shopId') or claims.get('shopId'))
    shop_id = shop.id
    owner = is_owner()
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
            raise ValueError('An open shift is required before selling')
        shift_id = open_shift.id

    if shift_id:
        shift = Shift.query.get(shift_id)
        if not shift:
            raise ValueError('Shift not found')
        if shift.status != 'open':
            raise ValueError('Shift must be open')
        if shift.shop_id and shift.shop_id != shop_id:
            raise ValueError('Shift does not belong to this shop')
        if not owner and shift.cashier_id != user_id:
            raise ValueError('Shift does not belong to this cashier')

    txn = Transaction(
        id=data['id'],
        receipt_number=data['receiptNumber'],
        shift_id=shift_id,
        shop_id=shop_id,
        cashier_id=cashier_id,
        cashier_name=cashier_name,

        subtotal=float(data.get('subtotal', 0)),
        discount_total=float(data.get('discountTotal', 0)),
        tax_total=float(data.get('taxTotal', 0)),
        grand_total=float(data['grandTotal']),
        payment_method=data.get('paymentMethod', 'cash'),
        is_split_bill=bool(data.get('isSplitBill', False)),
        status='completed',
        created_at=(
            datetime.fromisoformat(data['createdAt'])
            if data.get('createdAt') else datetime.utcnow()
        ),
        synced_at=datetime.utcnow(),
    )
    db.session.add(txn)
    db.session.flush()

    for item_data in data.get('items', []):
        item = TransactionItem(
            transaction_id=txn.id,
            product_id=item_data.get('productId'),
            product_code=item_data['productCode'],
            product_name=item_data['productName'],
            quantity=int(item_data['quantity']),
            unit_price=float(item_data['unitPrice']),
            discount=float(item_data.get('discount', 0)),
            line_total=float(item_data['lineTotal']),
        )
        db.session.add(item)

        # Deduct stock from the selling shop and write audit movement.
        if item_data.get('productId'):
            product = Product.query.get(item_data['productId'])
            if product:
                if not product.is_active:
                    raise ValueError(f'Product is inactive: {product.code}')
                apply_stock_movement(
                    shop_id=shop_id,
                    product_id=product.id,
                    movement_type='sale',
                    quantity=-item.quantity,
                    user_id=user_id,
                    reason='Sale',
                    reference_type='transaction',
                    reference_id=txn.id,
                    reorder_level=product.reorderLevel,
                )

    for pmt_data in data.get('payments', []):
        pmt = Payment(
            transaction_id=txn.id,
            method=pmt_data['method'],
            amount=float(pmt_data['amount']),
            reference=pmt_data.get('reference', ''),
            phone_number=pmt_data.get('phoneNumber', ''),
            card_last4=pmt_data.get('cardLast4', ''),
        )
        db.session.add(pmt)

    # A Sandbox STK callback may arrive before or after this offline sale sync.
    # Attach an already-confirmed payment leg when it exists.
    from models import MpesaPayment
    confirmed_mpesa = MpesaPayment.query.filter_by(
        transaction_id=txn.id,
        status='matched',
    ).first()
    if confirmed_mpesa and not any(
        pmt_data.get('method') == 'mpesa' for pmt_data in data.get('payments', [])
    ):
        db.session.add(Payment(
            transaction_id=txn.id,
            method='mpesa',
            amount=confirmed_mpesa.amount,
            reference=confirmed_mpesa.provider_receipt_number or '',
            phone_number=confirmed_mpesa.phone_number,
        ))

    return txn


# ---------------------------------------------------------------------------
# Single transaction sync
# ---------------------------------------------------------------------------

@transactions_bp.route('', methods=['POST'])
@jwt_required()
def sync_transaction():
    """Receive one transaction from Flutter.  Idempotent on transaction id."""
    user_id = get_jwt_identity()
    claims = get_jwt()
    data = request.get_json() or {}

    if not data.get('id') or not data.get('receiptNumber') or 'grandTotal' not in data:
        return jsonify({'success': False, 'message': 'id, receiptNumber and grandTotal are required'}), 400

    # Idempotency: return existing record if already synced
    existing = Transaction.query.get(data['id'])
    if existing:
        return jsonify({'success': True, 'message': 'Already synced', 'data': existing.to_dict()}), 200
    receipt_owner = Transaction.query.filter_by(receipt_number=data['receiptNumber']).first()
    if receipt_owner:
        return jsonify({
            'success': False,
            'message': 'Receipt number already exists for another transaction',
            'existingTransactionId': receipt_owner.id,
        }), 409

    try:
        txn = _build_transaction(data, user_id, claims)
        db.session.commit()
        return jsonify({'success': True, 'data': txn.to_dict()}), 201
    except ValueError as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ---------------------------------------------------------------------------
# Batch sync (for offline queues)
# ---------------------------------------------------------------------------

@transactions_bp.route('/batch', methods=['POST'])
@jwt_required()
def sync_batch():
    """Receive many transactions at once.  Each is idempotent individually."""
    user_id = get_jwt_identity()
    claims = get_jwt()
    data = request.get_json() or {}
    transactions_data = data.get('transactions', [])

    results = {'synced': 0, 'skipped': 0, 'failed': 0, 'errors': []}

    for txn_data in transactions_data:
        if Transaction.query.get(txn_data.get('id')):
            results['skipped'] += 1
            continue
        receipt_owner = Transaction.query.filter_by(receipt_number=txn_data.get('receiptNumber')).first()
        if receipt_owner:
            results['failed'] += 1
            results['errors'].append(
                f"{txn_data.get('id', '?')}: receiptNumber already used by {receipt_owner.id}"
            )
            continue
        try:
            _build_transaction(txn_data, user_id, claims)
            db.session.commit()
            results['synced'] += 1
        except ValueError as e:
            db.session.rollback()
            results['failed'] += 1
            results['errors'].append(f"{txn_data.get('id', '?')}: {str(e)}")
        except Exception as e:
            db.session.rollback()
            results['failed'] += 1
            results['errors'].append(f"{txn_data.get('id', '?')}: {str(e)}")

    return jsonify({'success': True, 'results': results}), 200


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

@transactions_bp.route('', methods=['GET'])
@jwt_required()
def list_transactions():
    """List transactions.  Owner sees all; cashier sees only their own."""
    user_id = get_jwt_identity()
    claims = get_jwt()

    query = Transaction.query
    if claims.get('role') != 'owner':
        query = query.filter_by(cashier_id=user_id)

    shift_id = request.args.get('shiftId')
    shop_id = request.args.get('shopId')
    date_from = request.args.get('dateFrom')
    date_to = request.args.get('dateTo')

    if shift_id:
        query = query.filter_by(shift_id=shift_id)
    if shop_id and is_owner():
        query = query.filter_by(shop_id=shop_id)
    if date_from:
        query = query.filter(Transaction.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(Transaction.created_at <= datetime.fromisoformat(date_to))

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    paginated = query.order_by(Transaction.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        'success': True,
        'data': [t.to_dict() for t in paginated.items],
        'total': paginated.total,
        'pages': paginated.pages,
        'currentPage': page,
    }), 200


@transactions_bp.route('/<transaction_id>', methods=['GET'])
@jwt_required()
def get_transaction(transaction_id):
    user_id = get_jwt_identity()
    claims = get_jwt()
    txn = Transaction.query.get(transaction_id)
    if not txn:
        return jsonify({'success': False, 'message': 'Transaction not found'}), 404
    if claims.get('role') != 'owner' and txn.cashier_id != user_id:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    return jsonify({'success': True, 'data': txn.to_dict()}), 200


@transactions_bp.route('/<transaction_id>/void', methods=['POST'])
@jwt_required()
def void_transaction(transaction_id):
    """Void a completed transaction and restore stock to the original shop."""
    owner_error = owner_required_response()
    if owner_error:
        return owner_error

    user_id = get_jwt_identity()
    data = request.get_json() or {}
    reason = data.get('reason', '').strip()
    if not reason:
        return jsonify({'success': False, 'message': 'reason is required'}), 400

    txn = Transaction.query.get(transaction_id)
    if not txn:
        return jsonify({'success': False, 'message': 'Transaction not found'}), 404
    if txn.status == 'voided':
        return jsonify({'success': False, 'message': 'Transaction is already voided'}), 400
    if txn.status != 'completed':
        return jsonify({'success': False, 'message': 'Only completed transactions can be voided'}), 400
    if not txn.shop_id:
        return jsonify({'success': False, 'message': 'Transaction has no shop and cannot restore stock safely'}), 400

    try:
        for item in txn.items:
            if not item.product_id:
                continue
            apply_stock_movement(
                shop_id=txn.shop_id,
                product_id=item.product_id,
                movement_type='void',
                quantity=item.quantity,
                user_id=user_id,
                reason=reason,
                reference_type='transaction_void',
                reference_id=txn.id,
            )

        txn.status = 'voided'
        db.session.commit()
        return jsonify({'success': True, 'data': txn.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
