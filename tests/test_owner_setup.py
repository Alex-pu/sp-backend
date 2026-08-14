from models import User


def test_initial_setup_stores_owner_contact_details(client, app):
    response = client.post('/api/auth/setup', json={
        'name': 'Owner',
        'email': 'owner@example.com',
        'phone': '+254712345678',
        'pin': '1234',
        'shopName': 'Main Shop',
        'shopLocation': 'Nairobi',
    })

    assert response.status_code == 201
    body = response.get_json()
    assert body['user']['name'] == 'Owner'
    assert body['user']['email'] == 'owner@example.com'
    assert body['user']['phone'] == '+254712345678'

    with app.app_context():
        owner = User.query.filter_by(name='Owner').one()
        assert owner.email == 'owner@example.com'
        assert owner.phone == '+254712345678'


def test_initial_setup_requires_owner_email(client):
    response = client.post('/api/auth/setup', json={
        'name': 'Owner',
        'email': 'owner@example.com',
        'pin': '1234',
        'shopName': 'Main Shop',
    })

    assert response.status_code == 400
    assert response.get_json()['message'] == 'Name, email, phone and PIN are required'
