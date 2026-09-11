import base64
from datetime import datetime
import os

import requests


class DarajaError(RuntimeError):
    pass


def normalize_mpesa_phone(value):
    digits = ''.join(character for character in str(value or '') if character.isdigit())
    if digits.startswith('254') and len(digits) == 12 and digits[3] in '17':
        return digits
    if digits.startswith('0') and len(digits) == 10 and digits[1] in '17':
        return f'254{digits[1:]}'
    if len(digits) == 9 and digits[0] in '17':
        return f'254{digits}'
    return None


def daraja_enabled():
    return os.environ.get('MPESA_ENABLED', '').lower() == 'true'


def _setting(name, required=True):
    value = os.environ.get(name, '').strip()
    if required and not value:
        raise DarajaError(f'Missing Daraja setting: {name}')
    return value


def _base_url():
    return os.environ.get(
        'MPESA_BASE_URL',
        'https://sandbox.safaricom.co.ke',
    ).rstrip('/')


def _timeout():
    return float(os.environ.get('MPESA_TIMEOUT_SECONDS', '20'))


def _access_token():
    try:
        response = requests.get(
            f'{_base_url()}/oauth/v1/generate',
            params={'grant_type': 'client_credentials'},
            auth=(_setting('MPESA_CONSUMER_KEY'), _setting('MPESA_CONSUMER_SECRET')),
            timeout=_timeout(),
        )
        response.raise_for_status()
        token = response.json().get('access_token')
    except requests.RequestException as error:
        raise DarajaError(f'Daraja OAuth request failed: {error}') from error
    if not token:
        raise DarajaError('Daraja OAuth response did not include an access token')
    return token


def stk_push(*, amount, phone_number, account_reference, transaction_description):
    phone_number = normalize_mpesa_phone(phone_number)
    if not phone_number:
        raise DarajaError('Enter a valid Kenyan M-Pesa number, for example 0712345678')
    shortcode = _setting('MPESA_SHORTCODE')
    passkey = _setting('MPESA_PASSKEY')
    callback_url = _setting('MPESA_STK_CALLBACK_URL')
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    password = base64.b64encode(
        f'{shortcode}{passkey}{timestamp}'.encode('utf-8')
    ).decode('ascii')
    payload = {
        'BusinessShortCode': shortcode,
        'Password': password,
        'Timestamp': timestamp,
        'TransactionType': 'CustomerPayBillOnline',
        'Amount': int(round(float(amount))),
        'PartyA': str(phone_number),
        'PartyB': shortcode,
        'PhoneNumber': str(phone_number),
        'CallBackURL': callback_url,
        'AccountReference': account_reference,
        'TransactionDesc': transaction_description[:20],
    }
    try:
        response = requests.post(
            f'{_base_url()}/mpesa/stkpush/v1/processrequest',
            json=payload,
            headers={'Authorization': f'Bearer {_access_token()}'},
            timeout=_timeout(),
        )
        response.raise_for_status()
        result = response.json()
    except requests.RequestException as error:
        raise DarajaError(f'Daraja STK request failed: {error}') from error
    if result.get('ResponseCode') not in (None, '0', 0):
        raise DarajaError(result.get('ResponseDescription', 'Daraja rejected STK request'))
    if not result.get('CheckoutRequestID'):
        raise DarajaError('Daraja STK response did not include CheckoutRequestID')
    return result


def register_c2b_urls():
    shortcode = _setting('MPESA_SHORTCODE')
    validation_url = _setting('MPESA_C2B_VALIDATION_URL')
    confirmation_url = _setting('MPESA_C2B_CONFIRMATION_URL')
    payload = {
        'ShortCode': shortcode,
        'ResponseType': 'Completed',
        'ConfirmationURL': confirmation_url,
        'ValidationURL': validation_url,
    }
    try:
        response = requests.post(
            f'{_base_url()}/mpesa/c2b/v1/registerurl',
            json=payload,
            headers={'Authorization': f'Bearer {_access_token()}'},
            timeout=_timeout(),
        )
        response.raise_for_status()
        result = response.json()
    except requests.RequestException as error:
        raise DarajaError(f'Daraja C2B registration failed: {error}') from error
    if result.get('ResponseCode') not in (None, '0', 0):
        raise DarajaError(result.get('ResponseDescription', 'Daraja rejected C2B registration'))
    return result