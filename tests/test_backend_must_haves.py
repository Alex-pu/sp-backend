from models import Product, ShopInventory, StockMovement, Transaction, db


def sale_payload(seed, **overrides):
    payload = {
        'id': 'txn-1',
        'receiptNumber': 'R-1',
        'shopId': seed['shop_a_id'],
        'grandTotal': 100,
        'items': [{
            'productId': seed['product_id'],
            'productCode': seed['product_code'],
            'productName': seed['product_name'],
            'quantity': 1,
            'unitPrice': 100,
            'lineTotal': 100,
        }],
        'payments': [{'method': 'cash', 'amount': 100}],
    }
    payload.update(overrides)
    return payload


def open_shift(client, headers, opening_float=100):
    response = client.post('/api/shifts', json={'openingFloat': opening_float}, headers=headers)
    assert response.status_code == 201
    return response.get_json()['data']


def stock_for(shop_id, product_id):
    return ShopInventory.query.filter_by(shop_id=shop_id, product_id=product_id).one().stock_level


def test_cashier_sale_requires_open_shift(client, seed, mary_headers):
    response = client.post('/api/transactions', json=sale_payload(seed), headers=mary_headers)

    assert response.status_code == 400
    assert response.get_json()['message'] == 'An open shift is required before selling'


def test_sale_reduces_only_cashier_shop_stock(client, seed, mary_headers):
    open_shift(client, mary_headers)

    response = client.post('/api/transactions', json=sale_payload(seed), headers=mary_headers)

    assert response.status_code == 201
    assert stock_for(seed['shop_a_id'], seed['product_id']) == 9
    assert stock_for(seed['shop_b_id'], seed['product_id']) == 7
    movement = StockMovement.query.filter_by(type='sale').one()
    assert movement.shop_id == seed['shop_a_id']
    assert movement.stock_before == 10
    assert movement.stock_after == 9


def test_cashier_cannot_spoof_another_shop(client, seed, mary_headers):
    open_shift(client, mary_headers)
    payload = sale_payload(seed, shopId=seed['shop_b_id'])

    response = client.post('/api/transactions', json=payload, headers=mary_headers)

    assert response.status_code == 400
    assert response.get_json()['message'] == 'Unauthorized shop'


def test_void_restores_stock_and_blocks_double_void(client, seed, mary_headers, owner_headers):
    open_shift(client, mary_headers)
    client.post('/api/transactions', json=sale_payload(seed), headers=mary_headers)

    cashier_void = client.post('/api/transactions/txn-1/void', json={'reason': 'mistake'}, headers=mary_headers)
    owner_void = client.post('/api/transactions/txn-1/void', json={'reason': 'wrong item'}, headers=owner_headers)
    double_void = client.post('/api/transactions/txn-1/void', json={'reason': 'again'}, headers=owner_headers)

    assert cashier_void.status_code == 403
    assert owner_void.status_code == 200
    assert double_void.status_code == 400
    assert stock_for(seed['shop_a_id'], seed['product_id']) == 10
    assert Transaction.query.get('txn-1').status == 'voided'
    assert StockMovement.query.filter_by(type='void').one().stock_after == 10


def test_receipt_number_conflict_is_rejected(client, seed, mary_headers):
    open_shift(client, mary_headers)
    first = client.post('/api/transactions', json=sale_payload(seed), headers=mary_headers)
    second = client.post(
        '/api/transactions',
        json=sale_payload(seed, id='txn-2', receiptNumber='R-1'),
        headers=mary_headers,
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.get_json()['existingTransactionId'] == 'txn-1'


def test_product_archive_hides_from_cashier_and_blocks_sale(client, seed, mary_headers, owner_headers):
    open_shift(client, mary_headers)
    archive = client.put(f"/api/products/{seed['product_id']}", json={'isActive': False}, headers=owner_headers)
    lookup = client.get('/api/products/code/COKE500', headers=mary_headers)
    sale = client.post('/api/transactions', json=sale_payload(seed), headers=mary_headers)

    assert archive.status_code == 200
    assert lookup.status_code == 404
    assert sale.status_code == 400
    assert 'Product is inactive' in sale.get_json()['message']


def test_owner_can_create_product_with_barcode_and_initial_stock(client, seed, owner_headers):
    response = client.post(
        '/api/products',
        json={
            'code': '6161101234567',
            'name': 'New Product',
            'sellingPrice': 125.5,
            'stockLevel': 4,
            'shopId': seed['shop_a_id'],
        },
        headers=owner_headers,
    )

    assert response.status_code == 201
    assert response.get_json()['data']['code'] == '6161101234567'
    product = Product.query.filter_by(code='6161101234567').one()
    assert stock_for(seed['shop_a_id'], product.id) == 4

    duplicate = client.post(
        '/api/products',
        json={'code': '6161101234567', 'name': 'Duplicate', 'sellingPrice': 1},
        headers=owner_headers,
    )
    assert duplicate.status_code == 409


def test_low_stock_and_bootstrap(client, seed, mary_headers, owner_headers):
    inventory = ShopInventory.query.filter_by(shop_id=seed['shop_a_id'], product_id=seed['product_id']).one()
    inventory.stock_level = 5
    db.session.commit()

    low = client.get('/api/stock/low', headers=mary_headers)
    bootstrap = client.get('/api/sync/bootstrap', headers=mary_headers)
    owner_low_b = client.get(f"/api/stock/low?shopId={seed['shop_b_id']}", headers=owner_headers)

    assert low.status_code == 200
    assert low.get_json()['data'][0]['code'] == 'COKE500'
    assert bootstrap.status_code == 200
    assert bootstrap.get_json()['shop']['id'] == seed['shop_a_id']
    assert bootstrap.get_json()['products'][0]['stockLevel'] == 5
    assert owner_low_b.status_code == 200
