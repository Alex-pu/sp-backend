from datetime import datetime, timedelta

from models import DeviceInvite, db


def create_invite(client, headers, shop_id, **overrides):
    payload = {'shopId': shop_id, 'deviceLabel': 'Till phone'}
    payload.update(overrides)
    return client.post('/api/device-invites', json=payload, headers=headers)


def test_owner_can_create_and_accept_device_invite(client, seed, owner_headers):
    created = create_invite(client, owner_headers, seed['shop_a_id'])
    body = created.get_json()
    token = body['token']

    preview = client.get(f'/api/device-invites/{token}')
    accepted = client.post(
        f'/api/device-invites/{token}/accept',
        json={'deviceId': 'phone-1', 'deviceLabel': 'Mary phone'},
    )

    assert created.status_code == 201
    assert body['data']['shopId'] == seed['shop_a_id']
    assert body['link'].startswith('smartpos://pair?token=')
    assert preview.status_code == 200
    assert preview.get_json()['data']['shop']['id'] == seed['shop_a_id']
    assert accepted.status_code == 200
    assert accepted.get_json()['shop']['id'] == seed['shop_a_id']
    invite = DeviceInvite.query.get(body['data']['id'])
    assert invite.status == 'accepted'
    assert invite.accepted_device_id == 'phone-1'


def test_device_invite_is_one_time_use(client, seed, owner_headers):
    token = create_invite(client, owner_headers, seed['shop_a_id']).get_json()['token']

    first = client.post(f'/api/device-invites/{token}/accept', json={'deviceId': 'phone-1'})
    second = client.post(f'/api/device-invites/{token}/accept', json={'deviceId': 'phone-2'})

    assert first.status_code == 200
    assert second.status_code == 404


def test_cashier_cannot_create_device_invite(client, seed, mary_headers):
    response = create_invite(client, mary_headers, seed['shop_a_id'])

    assert response.status_code == 403


def test_expired_device_invite_cannot_be_used(client, seed, owner_headers):
    created = create_invite(client, owner_headers, seed['shop_a_id'])
    invite = DeviceInvite.query.get(created.get_json()['data']['id'])
    invite.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()

    preview = client.get(f"/api/device-invites/{created.get_json()['token']}")
    accepted = client.post(
        f"/api/device-invites/{created.get_json()['token']}/accept",
        json={'deviceId': 'phone-1'},
    )

    assert preview.status_code == 404
    assert accepted.status_code == 404
