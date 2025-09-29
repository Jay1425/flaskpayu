import json
from flask import Blueprint, request, current_app, jsonify

from models import db, Order, Payment, Ledger
from utils import verify_razorpay_signature, trigger_bbps_billpay

webhooks_bp = Blueprint('webhooks', __name__, url_prefix='/webhook')


@webhooks_bp.post('/razorpay')
def webhook_razorpay():
    # Razorpay sends X-Razorpay-Signature header for verification
    signature = request.headers.get('X-Razorpay-Signature', '')
    payload = request.get_data()  # raw body bytes

    if not verify_razorpay_signature(payload, signature, current_app.config['RAZORPAY_WEBHOOK_SECRET']):
        return jsonify({'ok': False, 'error': 'Invalid signature'}), 400

    event = request.json or {}
    event_type = event.get('event')
    entity = (event.get('payload') or {}).get('payment', {}).get('entity') or {}

    if event_type == 'payment.captured':
        rzp_order_id = entity.get('order_id')
        rzp_payment_id = entity.get('id')
        amount = entity.get('amount')
        order = Order.query.filter_by(razorpay_order_id=rzp_order_id).first()
        if order:
            order.status = 'RZP_CAPTURED'
            pay = Payment(order_id=order.id, payment_id=rzp_payment_id, method=entity.get('method'), status='CAPTURED', amount=amount, webhook_payload=json.dumps(event))
            db.session.add(pay)
            db.session.add(order)
            db.session.add(Ledger(order_id=order.id, entry_type='RZP_CAPTURED', message=rzp_payment_id))
            db.session.commit()

            # Trigger BBPS (idempotent by order uuid)
            idempo_key = f"bbps-{order.order_uuid}"
            result = trigger_bbps_billpay(order, idempotency_key=idempo_key)
            # Optionally update order status on immediate success
            if result.get('status') == 'SUCCESS':
                order.status = 'PAID'
            elif result.get('status') == 'PENDING':
                order.status = 'BBPS_PENDING'
            else:
                order.status = 'BBPS_FAILED'
            db.session.add(order)
            db.session.commit()

    return jsonify({'ok': True})


@webhooks_bp.post('/bbps')
def webhook_bbps():
    # Placeholder for aggregator callback
    data = request.json or {}
    order_uuid = data.get('order_uuid')
    status = data.get('status')  # SUCCESS/FAILED/PENDING
    order = Order.query.filter_by(order_uuid=order_uuid).first()
    if not order:
        return jsonify({'ok': False, 'error': 'Order not found'}), 404

    if status == 'SUCCESS':
        order.status = 'PAID'
    elif status == 'FAILED':
        order.status = 'BBPS_FAILED'
    else:
        order.status = 'BBPS_PENDING'
    db.session.add(order)
    db.session.add(Ledger(order_id=order.id, entry_type='BBPS_WEBHOOK', message=status))
    db.session.commit()

    return jsonify({'ok': True})
