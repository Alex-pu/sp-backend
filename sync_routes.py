from datetime import datetime
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from auth_utils import current_user, is_owner, resolve_accessible_shop
from models import Product, Shift
from routes import product_with_shop_stock

sync_bp = Blueprint('sync', __name__, url_prefix='/api/sync')


@sync_bp.route('/bootstrap', methods=['GET'])
@jwt_required()
def bootstrap():
    """Return the minimum data a mobile client needs after login."""
    user = current_user()
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404

    try:
        shop = resolve_accessible_shop(request.args.get('shopId'))
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    current_shift = Shift.query.filter_by(
        cashier_id=user.id,
        shop_id=shop.id,
        status='open',
    ).first()

    return jsonify({
        'success': True,
        'serverTime': datetime.utcnow().isoformat(),
        'user': user.to_dict(),
        'shop': shop.to_dict(),
        'role': user.role,
        'isOwner': is_owner(),
        'currentShift': current_shift.to_dict() if current_shift else None,
        'products': [product_with_shop_stock(product, shop.id) for product in products],
    }), 200
