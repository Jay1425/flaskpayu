import json
import uuid
import hmac
import hashlib
from typing import Dict, Any

import razorpay
import requests
from flask import current_app

from models import db, Ledger, BBPSPayment, IdempotencyKey


def get_razorpay_client():
    return razorpay.Client(auth=(current_app.config['RAZORPAY_KEY_ID'], current_app.config['RAZORPAY_KEY_SECRET']))


def create_razorpay_order(amount_paise: int, receipt_id: str) -> Dict[str, Any]:
    """Create Razorpay order using Orders API.
    Returns the created order dict from Razorpay.
    """
    client = get_razorpay_client()
    order_data = {
        'amount': amount_paise,
        'currency': 'INR',
        'receipt': receipt_id,
        'payment_capture': 1,  # auto-capture
    }
    order = client.order.create(data=order_data)
    # ledger
    db.session.add(Ledger(order_id=None, entry_type='RZP_ORDER_CREATED', message=f"rzp_order_id={order.get('id')} receipt={receipt_id}"))
    db.session.commit()
    return order


def verify_razorpay_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify Razorpay webhook signature."""
    expected = hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def trigger_bbps_billpay(order, idempotency_key: str) -> Dict[str, Any]:
    """Trigger BBPS payment via aggregator API. This is a stub with a generic request.
    Replace with your aggregator's API spec. Demonstrates idempotency via a custom header.
    """
    # Idempotency: skip if we've already used this key
    if IdempotencyKey.query.filter_by(key=idempotency_key).first():
        db.session.add(Ledger(order_id=order.id, entry_type='BBPS_IDEMPOTENT_HIT', message=idempotency_key))
        db.session.commit()
        return {'status': 'ALREADY_TRIGGERED', 'data': {}}

    base_url = current_app.config['BBPS_BASE_URL']
    url = f"{base_url}/v1/pgvcl/pay"
    headers = {
        'Authorization': f"Bearer {current_app.config['BBPS_API_KEY']}",
        'X-Idempotency-Key': idempotency_key,
        'Content-Type': 'application/json',
    }
    payload = {
        'aggregator_id': current_app.config['BBPS_AGGREGATOR_ID'],
        'biller_code': current_app.config['BILLER_CODE'],
        'consumer_id': order.user.consumer_id,
        'amount': order.amount / 100.0,
        'request_id': str(uuid.uuid4()),
        'order_uuid': order.order_uuid,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        data = resp.json() if resp.headers.get('content-type', '').startswith('application/json') else {'text': resp.text}
        status = 'SUCCESS' if resp.status_code in (200, 201) else 'PENDING' if resp.status_code in (202,) else 'FAILED'
    except Exception as e:
        data = {'error': str(e)}
        status = 'FAILED'

    # Record idempotency key usage
    db.session.add(IdempotencyKey(key=idempotency_key))
    bbps = BBPSPayment(order_id=order.id, status=status, response_payload=json.dumps(data), request_id=payload['request_id'], bbps_txn_id=data.get('bbps_txn_id'))
    db.session.add(bbps)
    db.session.add(Ledger(order_id=order.id, entry_type='BBPS_TRIGGERED', message=f"status={status}"))
    db.session.commit()
    return {'status': status, 'data': data}


def poll_bbps_status(request_id: str) -> Dict[str, Any]:
    """Optional polling for async aggregators. Stub implementation."""
    base_url = current_app.config['BBPS_BASE_URL']
    url = f"{base_url}/v1/pgvcl/status/{request_id}"
    headers = {'Authorization': f"Bearer {current_app.config['BBPS_API_KEY']}"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        return resp.json()
    except Exception as e:
        return {'error': str(e)}


def generate_receipt_pdf(order_id: int) -> bytes:
    """Optional: generate a simple PDF as bytes. Not implemented; return None to skip."""
    return None


# -------------------------- PayU helpers --------------------------

def payu_hash_string(params: Dict[str, Any], salt: str) -> str:
    """Create PayU request hash using fields: key|txnid|amount|productinfo|firstname|email|||||||||||salt"""
    keys = ['key', 'txnid', 'amount', 'productinfo', 'firstname', 'email']
    raw = '|'.join(str(params.get(k, '')) for k in keys) + '|' + ('|' * 10) + salt
    return hashlib.sha512(raw.encode('utf-8')).hexdigest()


def build_payu_params(order, user) -> Dict[str, Any]:
    cfg = current_app.config
    amount_rupees = f"{order.amount/100:.2f}"
    txnid = order.order_uuid
    data = {
        'key': cfg['PAYU_MERCHANT_KEY'],
        'txnid': txnid,
        'amount': amount_rupees,
        'productinfo': f"PGVCL Bill {user.consumer_id}",
        'firstname': user.name,
        'email': user.email,
        'phone': user.phone,
        'surl': cfg['PAYU_SUCCESS_URL'],
        'furl': cfg['PAYU_FAILURE_URL'],
        'udf1': user.consumer_id,
        'udf2': order.order_uuid,
    }
    data['hash'] = payu_hash_string(data, cfg['PAYU_SALT'])
    return data


def payu_verify_response_hash(resp: Dict[str, Any], salt: str) -> bool:
    """Verify PayU response hash: hash = sha512(salt|status|||||||||||email|firstname|productinfo|amount|txnid|key)
    Depending on integration docs; this uses the reverse hash formula commonly documented.
    """
    parts = [
        salt,
        resp.get('status', ''),
    ] + [''] * 10 + [
        resp.get('email', ''),
        resp.get('firstname', ''),
        resp.get('productinfo', ''),
        str(resp.get('amount', '')),
        resp.get('txnid', ''),
        resp.get('key', ''),
    ]
    raw = '|'.join(parts)
    expected = hashlib.sha512(raw.encode('utf-8')).hexdigest()
    return hmac.compare_digest(expected, str(resp.get('hash', ''))) 
