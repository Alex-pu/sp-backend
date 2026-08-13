from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from models import Shop, db

shops_bp = Blueprint('shops', __name__, url_prefix='/api/shops')


def _owner_required():
    return get_jwt().get('role') == 'owner'


@shops_bp.route('', methods=['GET'])
@jwt_required()
def list_shops():
    """List active shops. Owner only for now."""
    if not _owner_required():
        return jsonify({'success': False, 'message': 'Owner access required'}), 403

    shops = Shop.query.order_by(Shop.name).all()
    return jsonify({'success': True, 'data': [shop.to_dict() for shop in shops]}), 200


@shops_bp.route('', methods=['POST'])
@jwt_required()
def create_shop():
    """Create a shop/branch. Owner only."""
    if not _owner_required():
        return jsonify({'success': False, 'message': 'Owner access required'}), 403

    data = request.get_json() or {}
    name = data.get('name', '').strip()
    location = data.get('location', '').strip()

    if not name:
        return jsonify({'success': False, 'message': 'Shop name is required'}), 400
    if Shop.query.filter(db.func.lower(Shop.name) == name.lower()).first():
        return jsonify({'success': False, 'message': 'A shop with that name already exists'}), 409

    shop = Shop(name=name, location=location)
    db.session.add(shop)
    db.session.commit()
    return jsonify({'success': True, 'data': shop.to_dict()}), 201


@shops_bp.route('/<shop_id>', methods=['PUT'])
@jwt_required()
def update_shop(shop_id):
    """Update basic shop details. Owner only."""
    if not _owner_required():
        return jsonify({'success': False, 'message': 'Owner access required'}), 403

    shop = Shop.query.get(shop_id)
    if not shop:
        return jsonify({'success': False, 'message': 'Shop not found'}), 404

    data = request.get_json() or {}
    if 'name' in data:
        name = data['name'].strip()
        if not name:
            return jsonify({'success': False, 'message': 'Shop name cannot be empty'}), 400
        duplicate = Shop.query.filter(
            db.func.lower(Shop.name) == name.lower(),
            Shop.id != shop_id,
        ).first()
        if duplicate:
            return jsonify({'success': False, 'message': 'A shop with that name already exists'}), 409
        shop.name = name
    if 'location' in data:
        shop.location = data['location'].strip()
    if 'isActive' in data:
        shop.is_active = bool(data['isActive'])

    db.session.commit()
    return jsonify({'success': True, 'data': shop.to_dict()}), 200
