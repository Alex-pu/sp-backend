import base64

import daraja_client


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_normalize_mpesa_phone_accepts_common_kenyan_formats():
    assert daraja_client.normalize_mpesa_phone('0712 345 678') == '254712345678'
    assert daraja_client.normalize_mpesa_phone('+254712345678') == '254712345678'
    assert daraja_client.normalize_mpesa_phone('712345678') == '254712345678'
    assert daraja_client.normalize_mpesa_phone('12345') is None


def test_sandbox_stk_push_builds_daraja_request(monkeypatch):
    monkeypatch.setenv('MPESA_BASE_URL', 'https://sandbox.example')
    monkeypatch.setenv('MPESA_CONSUMER_KEY', 'consumer-key')
    monkeypatch.setenv('MPESA_CONSUMER_SECRET', 'consumer-secret')
    monkeypatch.setenv('MPESA_SHORTCODE', '174379')
    monkeypatch.setenv('MPESA_PASSKEY', 'passkey')
    monkeypatch.setenv('MPESA_STK_CALLBACK_URL', 'https://pos.example/callback')
    calls = []

    def fake_get(url, **kwargs):
        calls.append(('get', url, kwargs))
        return FakeResponse({'access_token': 'token'})

    def fake_post(url, **kwargs):
        calls.append(('post', url, kwargs))
        return FakeResponse({
            'ResponseCode': '0',
            'CheckoutRequestID': 'ws_CO_123',
        })

    monkeypatch.setattr(daraja_client.requests, 'get', fake_get)
    monkeypatch.setattr(daraja_client.requests, 'post', fake_post)

    result = daraja_client.stk_push(
        amount=100,
        phone_number='254712345678',
        account_reference='S01',
        transaction_description='POS S01',
    )

    assert result['CheckoutRequestID'] == 'ws_CO_123'
    assert calls[0][0] == 'get'
    request = calls[1][2]['json']
    assert request['BusinessShortCode'] == '174379'
    assert request['AccountReference'] == 'S01'
    assert request['Amount'] == 100
    assert request['CallBackURL'] == 'https://pos.example/callback'
    assert calls[1][2]['headers']['Authorization'] == 'Bearer token'
    assert base64.b64decode(request['Password']).decode().startswith('174379passkey')