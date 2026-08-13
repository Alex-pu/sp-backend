from datetime import datetime, timedelta
import hashlib
import secrets

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from auth_utils import owner_required_response
from models import DeviceInvite, Shop, db

device_invites_bp = Blueprint('device_invites', __name__, url_prefix='/api/device-invites')


def _hash_token(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _find_invite(token):
    if not token:
        return None
    return DeviceInvite.query.filter_by(token_hash=_hash_token(token)).first()


@device_invites_bp.route('', methods=['POST'])
@jwt_required()
def create_invite():
    """Create a one-time shop pairing invite. Owner only."""
    owner_required = owner_required_response()
    if owner_required:
        return owner_required

    data = request.get_json() or {}
    shop_id = data.get('shopId')
    expires_in_hours = int(data.get('expiresInHours') or 24)
    device_label = data.get('deviceLabel', '').strip()

    if not shop_id:
        return jsonify({'success': False, 'message': 'shopId is required'}), 400
    if expires_in_hours < 1 or expires_in_hours > 168:
        return jsonify({'success': False, 'message': 'expiresInHours must be between 1 and 168'}), 400

    shop = Shop.query.get(shop_id)
    if not shop or not shop.is_active:
        return jsonify({'success': False, 'message': 'Shop not found or inactive'}), 404

    token = secrets.token_urlsafe(24)
    invite = DeviceInvite(
        shop_id=shop.id,
        token_hash=_hash_token(token),
        created_by=get_jwt_identity(),
        device_label=device_label,
        expires_at=datetime.utcnow() + timedelta(hours=expires_in_hours),
    )
    db.session.add(invite)
    db.session.commit()

    return jsonify({
        'success': True,
        'data': invite.to_dict(),
        'token': token,
        'link': f'smartpos://pair?token={token}',
    }), 201


@device_invites_bp.route('/<token>', methods=['GET'])
def get_invite(token):
    """Preview a pairing invite before accepting it."""
    invite = _find_invite(token)
    if not invite or not invite.is_valid():
        return jsonify({'success': False, 'message': 'Invite not found or expired'}), 404

    return jsonify({
        'success': True,
        'data': {
            'id': invite.id,
            'shop': invite.shop.to_dict(),
            'deviceLabel': invite.device_label,
            'expiresAt': invite.expires_at.isoformat(),
        },
    }), 200


@device_invites_bp.route('/<token>/accept', methods=['POST'])
def accept_invite(token):
    """Accept an invite and bind this mobile device to its shop."""
    invite = _find_invite(token)
    if not invite or not invite.is_valid():
        return jsonify({'success': False, 'message': 'Invite not found or expired'}), 404

    data = request.get_json() or {}
    device_id = data.get('deviceId', '').strip()
    device_label = data.get('deviceLabel', '').strip()
    if not device_id:
        return jsonify({'success': False, 'message': 'deviceId is required'}), 400

    invite.status = 'accepted'
    invite.accepted_at = datetime.utcnow()
    invite.accepted_device_id = device_id
    invite.accepted_device_label = device_label
    db.session.commit()

    return jsonify({
        'success': True,
        'shop': invite.shop.to_dict(),
        'device': {
            'id': device_id,
            'label': device_label,
        },
    }), 200
