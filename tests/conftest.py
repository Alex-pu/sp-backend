import os
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['JWT_SECRET_KEY'] = 'test-jwt-secret'
os.environ['CORS_ORIGINS'] = '*'

from app import create_app
from models import db, Product, Shop, User
from stock_routes import apply_stock_movement


@pytest.fixture
def app():
    app = create_app('development')
    app.config.update(TESTING=True)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seed(app):
    with app.app_context():
        shop_a = Shop(name='Branch A', payment_code='S01')
        shop_b = Shop(name='Branch B', payment_code='S02')

        owner = User(name='Admin', role='owner', shop=shop_a)
        owner.set_pin('1234')
        mary = User(name='Mary', role='cashier', shop=shop_a)
        mary.set_pin('1111')
        john = User(name='John', role='cashier', shop=shop_b)
        john.set_pin('2222')

        product = Product(
            code='COKE500',
            name='Coke 500ml',
            category='Drinks',
            costPrice=60,
            sellingPrice=100,
            stockLevel=0,
            reorderLevel=5,
        )

        db.session.add_all([shop_a, shop_b, owner, mary, john, product])
        db.session.commit()

        apply_stock_movement(shop_id=shop_a.id, product_id=product.id, movement_type='stock_received', quantity=10, user_id=owner.id)
        apply_stock_movement(shop_id=shop_b.id, product_id=product.id, movement_type='stock_received', quantity=7, user_id=owner.id)
        db.session.commit()

        return {
            'shop_a_id': shop_a.id,
            'shop_b_id': shop_b.id,
            'owner_id': owner.id,
            'mary_id': mary.id,
            'john_id': john.id,
            'product_id': product.id,
            'product_code': product.code,
            'product_name': product.name,
        }


def login(client, name, pin):
    response = client.post('/api/auth/login', json={'name': name, 'pin': pin})
    assert response.status_code == 200
    return {'Authorization': 'Bearer ' + response.get_json()['token']}


@pytest.fixture
def owner_headers(client, seed):
    return login(client, 'Admin', '1234')


@pytest.fixture
def mary_headers(client, seed):
    return login(client, 'Mary', '1111')


@pytest.fixture
def john_headers(client, seed):
    return login(client, 'John', '2222')
