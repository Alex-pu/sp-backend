from flask import jsonify
from flask_jwt_extended import get_jwt, get_jwt_identity
from models import Shop, User


def current_user():
    user_id = get_jwt_identity()
    return User.query.get(user_id) if user_id else None


def is_owner():
    return get_jwt().get('role') == 'owner'


def owner_required_response():
    if is_owner():
        return None
    return jsonify({'success': False, 'message': 'Owner access required'}), 403


def resolve_accessible_shop(requested_shop_id=None, *, allow_owner_any=True):
    """Return a shop the current user may operate in, or raise ValueError."""
    user = current_user()
    if not user:
        raise ValueError('User not found')

    if is_owner() and allow_owner_any:
        shop_id = requested_shop_id or user.shop_id
    else:
        if requested_shop_id and requested_shop_id != user.shop_id:
            raise ValueError('Unauthorized shop')
        shop_id = user.shop_id

    if not shop_id:
        raise ValueError('User is not assigned to a shop')

    shop = Shop.query.get(shop_id)
    if not shop or not shop.is_active:
        raise ValueError('Shop not found or inactive')
    return shop
