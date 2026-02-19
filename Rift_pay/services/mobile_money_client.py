import json
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from django.conf import settings


class MobileMoneyAPIError(Exception):
    pass


def _build_operator_config(operator):
    op = operator.upper().strip()
    if op == 'ORANGE':
        return {
            'name': 'ORANGE',
            'base_url': getattr(settings, 'ORANGE_MONEY_BASE_URL', '').strip(),
            'token': getattr(settings, 'ORANGE_MONEY_TOKEN', '').strip(),
            'collection_path': getattr(settings, 'ORANGE_MONEY_COLLECTION_PATH', '/api/collections').strip(),
            'disbursement_path': getattr(settings, 'ORANGE_MONEY_DISBURSEMENT_PATH', '/api/disbursements').strip(),
        }
    if op == 'MTN':
        return {
            'name': 'MTN',
            'base_url': getattr(settings, 'MTN_MONEY_BASE_URL', '').strip(),
            'token': getattr(settings, 'MTN_MONEY_TOKEN', '').strip(),
            'collection_path': getattr(settings, 'MTN_MONEY_COLLECTION_PATH', '/api/collections').strip(),
            'disbursement_path': getattr(settings, 'MTN_MONEY_DISBURSEMENT_PATH', '/api/disbursements').strip(),
        }
    raise MobileMoneyAPIError('Unsupported operator')


def _mobile_money_mode():
    return getattr(settings, 'MOBILE_MONEY_MODE', 'manual').strip().lower()


def _simulate_success(reference, operator):
    return {
        'status': 'SUCCESS',
        'operator_reference': f"sim-{operator.lower()}-{reference[-8:]}",
        'response_code': 'SIMULATED',
        'message': 'Simulated mobile money confirmation',
    }


def _post_operator_request(url, token, payload, idempotency_key):
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-Idempotency-Key': idempotency_key,
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'

    request = Request(
        url=url,
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method='POST'
    )

    try:
        with urlopen(request, timeout=getattr(settings, 'MOBILE_MONEY_API_TIMEOUT', 20)) as response:
            raw = response.read().decode('utf-8')
            data = json.loads(raw) if raw else {}
    except HTTPError as error:
        detail = error.read().decode('utf-8', errors='ignore')
        raise MobileMoneyAPIError(f'Operator API error ({error.code}): {detail[:400]}')
    except URLError as error:
        raise MobileMoneyAPIError(f'Operator API unreachable: {error.reason}')
    except TimeoutError:
        raise MobileMoneyAPIError('Operator API timeout reached')
    except json.JSONDecodeError:
        raise MobileMoneyAPIError('Operator API returned invalid JSON')

    return {
        'status': str(data.get('status', 'PENDING')).upper(),
        'operator_reference': str(data.get('operator_reference') or data.get('transaction_id') or '').strip(),
        'response_code': str(data.get('code', '')).strip(),
        'message': str(data.get('message', '')).strip(),
    }


def initiate_mobile_money_transaction(*, operator, direction, phone_number, amount, external_reference, customer_name):
    config = _build_operator_config(operator)
    mode = _mobile_money_mode()

    payload = {
        'reference': external_reference,
        'amount': str(amount),
        'currency': 'FCFA',
        'phone_number': phone_number,
        'customer_name': customer_name,
        'direction': direction,
    }

    if mode == 'manual' or not config['base_url']:
        return _simulate_success(external_reference, config['name'])

    path = config['collection_path'] if direction == 'DEPOSIT' else config['disbursement_path']
    endpoint = path.lstrip('/')
    url = urljoin(config['base_url'].rstrip('/') + '/', endpoint)

    response = _post_operator_request(
        url=url,
        token=config['token'],
        payload=payload,
        idempotency_key=external_reference,
    )

    if response['status'] not in {'PENDING', 'SUCCESS', 'FAILED'}:
        response['status'] = 'PENDING'

    return response
