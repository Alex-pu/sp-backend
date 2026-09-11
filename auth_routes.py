from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, get_jwt
from models import User, Shop, db
from shop_routes import next_payment_code

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


def _first_active_shop():
    return Shop.query.filter_by(is_active=True).order_by(Shop.created_at).first()


def _token_claims(user):
    return {
        'name': user.name,
        'email': user.email,
        'phone': user.phone,
        'role': user.role,
        'shopId': user.shop_id,
    }


# ---------------------------------------------------------------------------
# First-time setup
# ---------------------------------------------------------------------------

@auth_bp.route('/setup/status', methods=['GET'])
def setup_status():
    """Check whether the initial owner account has been created yet."""
    return jsonify({'needsSetup': User.query.count() == 0}), 200


@auth_bp.route('/setup', methods=['POST'])
def initial_setup():
    """Create the first owner account.  Blocked once any user exists."""
    if User.query.count() > 0:
        return jsonify({'success': False, 'message': 'Setup already completed'}), 403

    data = request.get_json() or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    phone = data.get('phone', '').strip()
    pin = str(data.get('pin', ''))

    if not name or not email or not phone or not pin:
        return jsonify({'success': False, 'message': 'Name, email, phone and PIN are required'}), 400
    if '@' not in email or '.' not in email.split('@')[-1]:
        return jsonify({'success': False, 'message': 'Valid email is required'}), 400
    if not _valid_phone(phone):
        return jsonify({'success': False, 'message': 'Valid phone is required'}), 400
    if not pin.isdigit() or len(pin) < 4 or len(pin) > 6:
        return jsonify({'success': False, 'message': 'PIN must be 4-6 digits'}), 400

    shop_name = data.get('shopName', 'Main Shop').strip() or 'Main Shop'
    shop = Shop(
        name=shop_name,
        location=data.get('shopLocation', '').strip(),
        payment_code=next_payment_code(),
    )
    db.session.add(shop)
    db.session.flush()

    user = User(name=name, email=email, phone=phone, role='owner', shop_id=shop.id)
    user.set_pin(pin)
    db.session.add(user)
    db.session.commit()

    token = create_access_token(
        identity=str(user.id),
        additional_claims=_token_claims(user)
    )
    return jsonify({'success': True, 'token': token, 'user': user.to_dict()}), 201


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@auth_bp.route('/login', methods=['POST'])
def login():
    """Authenticate with name + PIN, return a JWT."""
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    pin = str(data.get('pin', ''))

    if not name or not pin:
        return jsonify({'success': False, 'message': 'Name and PIN are required'}), 400

    user = User.query.filter(
        db.func.lower(User.name) == name.lower(),
        User.is_active == True
    ).first()

    if not user or not user.check_pin(pin):
        return jsonify({'success': False, 'message': 'Invalid name or PIN'}), 401

    token = create_access_token(
        identity=str(user.id),
        additional_claims=_token_claims(user)
    )
    return jsonify({'success': True, 'token': token, 'user': user.to_dict()}), 200


@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def me():
    """Return the profile of the authenticated user."""
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    return jsonify({'success': True, 'user': user.to_dict()}), 200


# ---------------------------------------------------------------------------
# User management (owner only)
# ---------------------------------------------------------------------------

@auth_bp.route('/users', methods=['GET'])
@jwt_required()
def list_users():
    """List all users.  Owner only."""
    claims = get_jwt()
    if claims.get('role') != 'owner':
        return jsonify({'success': False, 'message': 'Owner access required'}), 403

    users = User.query.order_by(User.name).all()
    return jsonify({'success': True, 'data': [u.to_dict() for u in users]}), 200


@auth_bp.route('/users', methods=['POST'])
@jwt_required()
def create_user():
    """Create a new cashier or owner account.  Owner only."""
    claims = get_jwt()
    if claims.get('role') != 'owner':
        return jsonify({'success': False, 'message': 'Owner access required'}), 403

    data = request.get_json() or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    phone = data.get('phone', '').strip()
    pin = str(data.get('pin', ''))
    role = data.get('role', 'cashier')
    shop_id = data.get('shopId')

    if not name or not pin:
        return jsonify({'success': False, 'message': 'Name and PIN are required'}), 400
    if not pin.isdigit() or len(pin) < 4 or len(pin) > 6:
        return jsonify({'success': False, 'message': 'PIN must be 4-6 digits'}), 400
    if role not in ('owner', 'cashier'):
        return jsonify({'success': False, 'message': 'Role must be owner or cashier'}), 400

    if User.query.filter(db.func.lower(User.name) == name.lower()).first():
        return jsonify({'success': False, 'message': 'A user with that name already exists'}), 409
    if email and User.query.filter(db.func.lower(User.email) == email).first():
        return jsonify({'success': False, 'message': 'A user with that email already exists'}), 409
    if phone and not _valid_phone(phone):
        return jsonify({'success': False, 'message': 'Valid phone is required'}), 400

    if shop_id:
        shop = Shop.query.get(shop_id)
        if not shop or not shop.is_active:
            return jsonify({'success': False, 'message': 'Shop not found or inactive'}), 400
    else:
        shop = _first_active_shop()
        if not shop:
            return jsonify({'success': False, 'message': 'Create a shop before adding users'}), 400
        shop_id = shop.id

    user = User(name=name, email=email or None, phone=phone or None, role=role, shop_id=shop_id)
    user.set_pin(pin)
    db.session.add(user)
    db.session.commit()

    return jsonify({'success': True, 'user': user.to_dict()}), 201


@auth_bp.route('/users/<user_id>', methods=['PUT'])
@jwt_required()
def update_user(user_id):
    """Update a user.  Owner can change anything; a cashier can only change their own PIN."""
    claims = get_jwt()
    current_user_id = get_jwt_identity()
    is_owner = claims.get('role') == 'owner'
    is_self = current_user_id == user_id

    if not is_owner and not is_self:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404

    data = request.get_json() or {}

    if 'pin' in data:
        new_pin = str(data['pin'])
        if not new_pin.isdigit() or len(new_pin) < 4 or len(new_pin) > 6:
            return jsonify({'success': False, 'message': 'PIN must be 4-6 digits'}), 400
        user.set_pin(new_pin)

    if is_owner:
        if 'name' in data:
            user.name = data['name'].strip()
        if 'email' in data:
            email = data['email'].strip().lower()
            if email and ('@' not in email or '.' not in email.split('@')[-1]):
                return jsonify({'success': False, 'message': 'Valid email is required'}), 400
            user.email = email or None
        if 'phone' in data:
            phone = data['phone'].strip()
            if phone and not _valid_phone(phone):
                return jsonify({'success': False, 'message': 'Valid phone is required'}), 400
            user.phone = phone or None
        if 'role' in data and data['role'] in ('owner', 'cashier'):
            user.role = data['role']
        if 'shopId' in data:
            shop_id = data.get('shopId')
            if shop_id:
                shop = Shop.query.get(shop_id)
                if not shop or not shop.is_active:
                    return jsonify({'success': False, 'message': 'Shop not found or inactive'}), 400
            user.shop_id = shop_id
        if 'isActive' in data:
            user.is_active = bool(data['isActive'])

    db.session.commit()
    return jsonify({'success': True, 'user': user.to_dict()}), 200


def _valid_phone(value):
    digits = ''.join(ch for ch in value if ch.isdigit())
    return 7 <= len(digits) <= 15
