import json
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from django.conf import settings


class BlockchainSyncError(Exception):
    pass


def sync_transaction(transaction_obj):
    base_url = settings.BLOCKCHAIN_API_BASE_URL.rstrip('/') + '/'
    endpoint = settings.BLOCKCHAIN_API_TRANSFER_PATH.lstrip('/')
    url = urljoin(base_url, endpoint)

    reference_id = f"tx-{transaction_obj.id}-{uuid.uuid4().hex[:8]}"

    payload = {
        'local_transaction_id': transaction_obj.id,
        'reference_id': reference_id,
        'sender_user_id': transaction_obj.sender.user_id,
        'receiver_user_id': transaction_obj.receiver.user_id,
        'amount': str(transaction_obj.amount),
        'currency': 'FCFA',
        'timestamp': transaction_obj.timestamp.isoformat(),
    }

    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-Idempotency-Key': str(transaction_obj.id),
    }

    api_key = settings.BLOCKCHAIN_API_KEY.strip()
    api_key_header = settings.BLOCKCHAIN_API_KEY_HEADER.strip() or 'X-API-Key'
    if api_key:
        headers[api_key_header] = api_key

    token = settings.BLOCKCHAIN_API_TOKEN.strip()
    if token:
        headers['Authorization'] = f'Bearer {token}'

    request = Request(
        url=url,
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method='POST'
    )

    try:
        with urlopen(request, timeout=settings.BLOCKCHAIN_API_TIMEOUT) as response:
            raw = response.read().decode('utf-8')
            data = json.loads(raw) if raw else {}
    except HTTPError as error:
        detail = error.read().decode('utf-8', errors='ignore')
        raise BlockchainSyncError(f'Blockchain API error ({error.code}): {detail}')
    except URLError as error:
        raise BlockchainSyncError(f'Blockchain API unreachable: {error.reason}')
    except TimeoutError:
        raise BlockchainSyncError('Blockchain API timeout reached')
    except json.JSONDecodeError:
        raise BlockchainSyncError('Blockchain API returned invalid JSON')

    return {
        'reference_id': data.get('reference_id', payload['reference_id']),
        'stellar_transaction_hash': data.get('stellar_transaction_hash', ''),
        'proof_hash': data.get('proof_hash', ''),
        'amount': data.get('amount', payload['amount']),
        'currency': data.get('currency', payload['currency']),
    }
