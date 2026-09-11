from datetime import datetime
import uuid

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from auth_utils import is_owner, resolve_accessible_shop
from daraja_client import (
    DarajaError,
    daraja_enabled,
    normalize_mpesa_phone,
    register_c2b_urls,
    stk_push,
)
from models import MpesaPayment, Payment, Settlement, Shop, Transaction, db


payments_bp = Blueprint('payments', __name__, url_prefix='/api/payments')


def owner_only():
    if not is_owner():
        return jsonify({'success': False, 'message': 'Owner access required'}), 403
    return None


def shop_balance(shop_id):
    confirmed = db.session.query(db.func.coalesce(db.func.sum(MpesaPayment.amount), 0)).filter(
        MpesaPayment.shop_id == shop_id,
        MpesaPayment.status == 'matched',
    ).scalar()
    released = db.session.query(db.func.coalesce(db.func.sum(Settlement.amount), 0)).filter(
        Settlement.shop_id == shop_id,
        Settlement.status.in_(['pending', 'completed']),
    ).scalar()
    return float(confirmed or 0) - float(released or 0)


@payments_bp.route('/requests', methods=['POST'])
@jwt_required()
def create_payment_request():
    data = request.get_json() or {}
    try:
        shop = resolve_accessible_shop(data.get('shopId'))
    except ValueError as error:
        return jsonify({'success': False, 'message': str(error)}), 400
    method = data.get('method', 'stk_push')
    amount = data.get('amount')
    if not shop or not shop.is_active:
        return jsonify({'success': False, 'message': 'Shop not found'}), 404
    if method not in ('stk_push', 'paybill'):
        return jsonify({'success': False, 'message': 'Unsupported payment method'}), 400
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'A valid amount is required'}), 400
    if amount <= 0:
        return jsonify({'success': False, 'message': 'Amount must be greater than zero'}), 400
    phone_number = normalize_mpesa_phone(data.get('phoneNumber')) if method == 'stk_push' else ''
    if method == 'stk_push' and not phone_number:
        return jsonify({
            'success': False,
            'message': 'Enter a valid Kenyan M-Pesa number, for example 0712345678',
        }), 400

    payment = MpesaPayment(
        shop_id=shop.id,
        transaction_id=data.get('transactionId'),
        method=method,
        amount=amount,
        account_reference=shop.payment_code or '',
        phone_number=phone_number,
        provider_request_id=None,
    )
    transaction_id = data.get('transactionId')
    if transaction_id:
        transaction = Transaction.query.get(transaction_id)
        if transaction and transaction.shop_id != shop.id:
            return jsonify({'success': False, 'message': 'Transaction does not belong to this shop'}), 400
    db.session.add(payment)
    if method == 'stk_push' and daraja_enabled():
        try:
            result = stk_push(
                amount=amount,
                phone_number=payment.phone_number,
                account_reference=payment.account_reference,
                transaction_description=f'POS {shop.payment_code}',
            )
            payment.provider_request_id = result['CheckoutRequestID']
            payment.status = 'pending'
        except DarajaError as error:
            db.session.rollback()
            return jsonify({'success': False, 'message': str(error)}), 502
    else:
        payment.provider_request_id = f'TEST-{uuid.uuid4()}'
    db.session.commit()
    return jsonify({
        'success': True,
        'mode': 'sandbox' if daraja_enabled() and method == 'stk_push' else 'test',
        'message': 'STK prompt sent' if daraja_enabled() and method == 'stk_push' else 'Payment request recorded; simulate a callback to confirm it',
        'data': payment.to_dict(),
    }), 201


@payments_bp.route('/callbacks/c2b', methods=['POST'])
def c2b_callback():
    """Accept a Daraja-shaped C2B callback; safe to replay by receipt number."""
    data = request.get_json() or {}
    receipt = str(data.get('TransID') or data.get('mpesaReceiptNumber') or '').strip()
    if not receipt:
        return jsonify({'ResultCode': 1, 'ResultDesc': 'TransID is required'}), 400
    existing = MpesaPayment.query.filter_by(provider_receipt_number=receipt).first()
    if existing:
        return jsonify({'ResultCode': 0, 'ResultDesc': 'Accepted', 'payment': existing.to_dict()}), 200

    try:
        amount = float(data.get('TransAmount', data.get('amount')))
    except (TypeError, ValueError):
        return jsonify({'ResultCode': 1, 'ResultDesc': 'A valid amount is required'}), 400
    account = str(data.get('BillRefNumber') or data.get('accountReference') or '').strip().upper()
    shop = Shop.query.filter(db.func.upper(Shop.payment_code) == account).first() if account else None
    checkout_id = data.get('CheckoutRequestID') or data.get('checkoutRequestId')
    payment = MpesaPayment.query.filter_by(provider_request_id=checkout_id).first() if checkout_id else None
    if payment and payment.status == 'pending':
        if payment.amount != amount:
            payment.status = 'failed'
            payment.failure_reason = 'Callback amount does not match request'
        else:
            payment.status = 'matched'
            payment.shop_id = payment.shop_id or (shop.id if shop else None)
            payment.confirmed_at = datetime.utcnow()
            payment.provider_receipt_number = receipt
            if payment.transaction_id:
                transaction = Transaction.query.get(payment.transaction_id)
                if transaction and not transaction.mpesa_payments:
                    db.session.add(Payment(
                        transaction_id=transaction.id,
                        method='mpesa',
                        amount=payment.amount,
                        reference=receipt,
                        phone_number=payment.phone_number,
                    ))
    else:
        payment = MpesaPayment(
            shop_id=shop.id if shop else None,
            method='paybill',
            amount=amount,
            account_reference=account,
            phone_number=str(data.get('MSISDN') or data.get('phoneNumber') or ''),
            status='unmatched',
            provider_receipt_number=receipt,
            raw_callback=data,
        )
        db.session.add(payment)
    if payment.raw_callback is None:
        payment.raw_callback = data
    db.session.commit()
    return jsonify({'ResultCode': 0, 'ResultDesc': 'Accepted', 'payment': payment.to_dict()}), 200


@payments_bp.route('/callbacks/stk', methods=['POST'])
def stk_callback():
    """Process the Daraja STK callback and confirm the matching request."""
    data = request.get_json() or {}
    callback = data.get('Body', {}).get('stkCallback', {})
    checkout_id = callback.get('CheckoutRequestID')
    payment = MpesaPayment.query.filter_by(provider_request_id=checkout_id).first()
    if not payment:
        return jsonify({'ResultCode': 0, 'ResultDesc': 'Accepted'}), 200
    if str(callback.get('ResultCode')) != '0':
        payment.status = 'failed'
        payment.failure_reason = callback.get('ResultDesc', 'STK payment failed')
        payment.raw_callback = data
        db.session.commit()
        return jsonify({'ResultCode': 0, 'ResultDesc': 'Accepted'}), 200

    metadata = {
        item.get('Name'): item.get('Value')
        for item in callback.get('CallbackMetadata', {}).get('Item', [])
    }
    receipt = str(metadata.get('MpesaReceiptNumber', '')).strip()
    if not receipt or payment.provider_receipt_number:
        return jsonify({'ResultCode': 0, 'ResultDesc': 'Accepted'}), 200
    if float(metadata.get('Amount', payment.amount)) != payment.amount:
        payment.status = 'failed'
        payment.failure_reason = 'Callback amount does not match request'
    else:
        payment.status = 'matched'
        payment.provider_receipt_number = receipt
        payment.phone_number = str(metadata.get('PhoneNumber', payment.phone_number))
        payment.confirmed_at = datetime.utcnow()
        if payment.transaction_id:
            transaction = Transaction.query.get(payment.transaction_id)
            if transaction and not transaction.mpesa_payments:
                db.session.add(Payment(
                    transaction_id=transaction.id,
                    method='mpesa',
                    amount=payment.amount,
                    reference=receipt,
                    phone_number=payment.phone_number,
                ))
    payment.raw_callback = data
    db.session.commit()
    return jsonify({'ResultCode': 0, 'ResultDesc': 'Accepted'}), 200


@payments_bp.route('/mpesa/register-callback', methods=['POST'])
@jwt_required()
def register_mpesa_callback():
    error = owner_only()
    if error:
        return error
    if not daraja_enabled():
        return jsonify({'success': False, 'message': 'MPESA_ENABLED is not true'}), 400
    try:
        result = register_c2b_urls()
    except DarajaError as error:
        return jsonify({'success': False, 'message': str(error)}), 502
    return jsonify({'success': True, 'data': result}), 200


@payments_bp.route('/unmatched', methods=['GET'])
@jwt_required()
def list_unmatched():
    error = owner_only()
    if error:
        return error
    shop_id = request.args.get('shopId')
    query = MpesaPayment.query.filter(MpesaPayment.status == 'unmatched')
    if shop_id:
        query = query.filter_by(shop_id=shop_id)
    return jsonify({'success': True, 'data': [p.to_dict() for p in query.order_by(MpesaPayment.created_at.desc()).all()]}), 200


@payments_bp.route('/<payment_id>', methods=['GET'])
@jwt_required()
def get_payment(payment_id):
    payment = MpesaPayment.query.get(payment_id)
    if not payment:
        return jsonify({'success': False, 'message': 'Payment not found'}), 404
    try:
        shop = resolve_accessible_shop(payment.shop_id)
    except ValueError as error:
        return jsonify({'success': False, 'message': str(error)}), 403
    if shop.id != payment.shop_id:
        return jsonify({'success': False, 'message': 'Payment access denied'}), 403
    return jsonify({'success': True, 'data': payment.to_dict()}), 200


@payments_bp.route('/<payment_id>/match', methods=['POST'])
@jwt_required()
def match_payment(payment_id):
    error = owner_only()
    if error:
        return error
    payment = MpesaPayment.query.get(payment_id)
    transaction_id = (request.get_json() or {}).get('transactionId')
    transaction = Transaction.query.get(transaction_id) if transaction_id else None
    if not payment or payment.status != 'unmatched':
        return jsonify({'success': False, 'message': 'Unmatched payment not found'}), 404
    if not transaction or (payment.shop_id and transaction.shop_id != payment.shop_id):
        return jsonify({'success': False, 'message': 'Transaction does not belong to this payment shop'}), 400
    if abs(transaction.grand_total - payment.amount) > 0.01:
        return jsonify({'success': False, 'message': 'Payment amount does not match transaction total'}), 400
    if transaction.mpesa_payments:
        return jsonify({'success': False, 'message': 'Transaction already has a matched M-Pesa payment'}), 409

    payment.transaction_id = transaction.id
    payment.shop_id = payment.shop_id or transaction.shop_id
    payment.status = 'matched'
    payment.matched_by = get_jwt_identity()
    payment.matched_at = datetime.utcnow()
    payment.confirmed_at = payment.confirmed_at or datetime.utcnow()
    db.session.add(Payment(
        transaction_id=transaction.id,
        method='mpesa',
        amount=payment.amount,
        reference=payment.provider_receipt_number or payment.account_reference,
        phone_number=payment.phone_number,
    ))
    db.session.commit()
    return jsonify({'success': True, 'data': payment.to_dict()}), 200


@payments_bp.route('/balances', methods=['GET'])
@jwt_required()
def balances():
    error = owner_only()
    if error:
        return error
    shops = Shop.query.filter_by(is_active=True).order_by(Shop.name).all()
    return jsonify({'success': True, 'data': [{
        'shopId': shop.id,
        'shopName': shop.name,
        'paymentCode': shop.payment_code,
        'availableBalance': shop_balance(shop.id),
    } for shop in shops]}), 200


@payments_bp.route('/settlements', methods=['POST'])
@jwt_required()
def request_settlement():
    error = owner_only()
    if error:
        return error
    data = request.get_json() or {}
    shop_id = data.get('shopId')
    destination_type = data.get('destinationType')
    destination = str(data.get('destination', '')).strip()
    try:
        amount = float(data.get('amount'))
    except (TypeError, ValueError):
        amount = 0
    if destination_type not in ('mpesa', 'bank') or not destination or amount <= 0:
        return jsonify({'success': False, 'message': 'Shop, destination, type, and valid amount are required'}), 400
    if amount > shop_balance(shop_id):
        return jsonify({'success': False, 'message': 'Settlement exceeds available shop balance'}), 400
    settlement = Settlement(
        shop_id=shop_id,
        amount=amount,
        destination_type=destination_type,
        destination=destination,
        requested_by=get_jwt_identity(),
        status='pending',
    )
    db.session.add(settlement)
    db.session.commit()
    return jsonify({'success': True, 'mode': 'test', 'data': settlement.to_dict()}), 201