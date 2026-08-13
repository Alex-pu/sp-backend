from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from auth_utils import current_user, is_owner, owner_required_response, resolve_accessible_shop
from models import Product, Shop, ShopInventory, StockMovement, User, db

stock_bp = Blueprint('stock', __name__, url_prefix='/api/stock')


def get_or_create_inventory(shop_id, product_id, reorder_level=None):
    inventory = ShopInventory.query.filter_by(
        shop_id=shop_id,
        product_id=product_id,
    ).first()
    if inventory:
        return inventory

    product = Product.query.get(product_id)
    inventory = ShopInventory(
        shop_id=shop_id,
        product_id=product_id,
        stock_level=0,
        reorder_level=int(reorder_level) if reorder_level is not None else (
            product.reorderLevel if product else 10
        ),
    )
    db.session.add(inventory)
    db.session.flush()
    return inventory


def apply_stock_movement(
    *,
    shop_id,
    product_id,
    movement_type,
    quantity,
    user_id=None,
    reason='',
    reference_type='',
    reference_id='',
    reorder_level=None,
    allow_zero=False,
):
    if quantity == 0 and not allow_zero:
        raise ValueError('quantity cannot be 0')

    inventory = get_or_create_inventory(shop_id, product_id, reorder_level)
    stock_before = inventory.stock_level
    stock_after = stock_before + quantity

    inventory.stock_level = stock_after
    movement = StockMovement(
        shop_id=shop_id,
        product_id=product_id,
        type=movement_type,
        quantity=quantity,
        stock_before=stock_before,
        stock_after=stock_after,
        reason=reason,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by=user_id,
    )
    db.session.add(movement)
    return inventory, movement


@stock_bp.route('/inventory', methods=['GET'])
@jwt_required()
def list_inventory():
    user_id = get_jwt_identity()
    user = current_user()
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404

    try:
        shop = resolve_accessible_shop(request.args.get('shopId'))
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    search = request.args.get('search')
    category = request.args.get('category')
    low_stock = request.args.get('lowStock') == 'true'

    query = ShopInventory.query.join(Product).filter(ShopInventory.shop_id == shop.id)
    if search:
        term = f"%{search}%"
        query = query.filter((Product.name.ilike(term)) | (Product.code.ilike(term)))
    if category and category.lower() != 'all':
        query = query.filter(Product.category == category)
    if low_stock:
        query = query.filter(ShopInventory.stock_level <= ShopInventory.reorder_level)

    items = query.order_by(Product.name).all()
    return jsonify({'success': True, 'shop': shop.to_dict(), 'data': [i.to_dict() for i in items]}), 200


@stock_bp.route('/receive', methods=['POST'])
@jwt_required()
def receive_stock():
    owner_error = owner_required_response()
    if owner_error:
        return owner_error

    user_id = get_jwt_identity()
    data = request.get_json() or {}
    product_id = data.get('productId')
    shop_id = data.get('shopId')
    quantity = int(data.get('quantity', 0))

    if not product_id or not shop_id:
        return jsonify({'success': False, 'message': 'productId and shopId are required'}), 400
    if quantity <= 0:
        return jsonify({'success': False, 'message': 'quantity must be greater than 0'}), 400
    if not Product.query.get(product_id):
        return jsonify({'success': False, 'message': 'Product not found'}), 404
    shop = Shop.query.get(shop_id)
    if not shop or not shop.is_active:
        return jsonify({'success': False, 'message': 'Shop not found or inactive'}), 400

    try:
        inventory, movement = apply_stock_movement(
            shop_id=shop_id,
            product_id=product_id,
            movement_type='stock_received',
            quantity=quantity,
            user_id=user_id,
            reason=data.get('reason', 'Stock received'),
            reference_type=data.get('referenceType', ''),
            reference_id=data.get('referenceId', ''),
            reorder_level=data.get('reorderLevel'),
        )
        db.session.commit()
        return jsonify({'success': True, 'inventory': inventory.to_dict(), 'movement': movement.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@stock_bp.route('/adjust', methods=['POST'])
@jwt_required()
def adjust_stock():
    owner_error = owner_required_response()
    if owner_error:
        return owner_error

    user_id = get_jwt_identity()
    data = request.get_json() or {}
    product_id = data.get('productId')
    shop_id = data.get('shopId')
    reason = data.get('reason', '').strip()

    if not product_id or not shop_id or 'newStockLevel' not in data:
        return jsonify({'success': False, 'message': 'productId, shopId and newStockLevel are required'}), 400
    if not reason:
        return jsonify({'success': False, 'message': 'reason is required'}), 400
    if not Product.query.get(product_id):
        return jsonify({'success': False, 'message': 'Product not found'}), 404
    shop = Shop.query.get(shop_id)
    if not shop or not shop.is_active:
        return jsonify({'success': False, 'message': 'Shop not found or inactive'}), 400

    try:
        inventory = get_or_create_inventory(shop_id, product_id, data.get('reorderLevel'))
        quantity = int(data['newStockLevel']) - inventory.stock_level
        inventory, movement = apply_stock_movement(
            shop_id=shop_id,
            product_id=product_id,
            movement_type='manual_adjustment',
            quantity=quantity,
            user_id=user_id,
            reason=reason,
            reference_type='manual_adjustment',
            reference_id=data.get('referenceId', ''),
            reorder_level=data.get('reorderLevel'),
            allow_zero=True,
        )
        db.session.commit()
        return jsonify({'success': True, 'inventory': inventory.to_dict(), 'movement': movement.to_dict()}), 200
    except ValueError as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@stock_bp.route('/movements', methods=['GET'])
@jwt_required()
def list_movements():
    user_id = get_jwt_identity()
    user = current_user()
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404

    try:
        shop = resolve_accessible_shop(request.args.get('shopId'))
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    query = StockMovement.query.filter_by(shop_id=shop.id)
    product_id = request.args.get('productId')
    movement_type = request.args.get('type')
    if product_id:
        query = query.filter_by(product_id=product_id)
    if movement_type:
        query = query.filter_by(type=movement_type)

    movements = query.order_by(StockMovement.created_at.desc()).limit(200).all()
    return jsonify({'success': True, 'shop': shop.to_dict(), 'data': [m.to_dict() for m in movements]}), 200


@stock_bp.route('/low', methods=['GET'])
@jwt_required()
def low_stock():
    user = current_user()
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404

    try:
        shop = resolve_accessible_shop(request.args.get('shopId'))
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    items = ShopInventory.query.join(Product).filter(
        ShopInventory.shop_id == shop.id,
        ShopInventory.stock_level <= ShopInventory.reorder_level,
        Product.is_active == True,
    ).order_by(Product.name).all()

    return jsonify({'success': True, 'shop': shop.to_dict(), 'data': [item.to_dict() for item in items]}), 200
