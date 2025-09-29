import os
import uuid
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from dotenv import load_dotenv

from config import Config
from models import db, User, Order, Payment, BBPSPayment, Ledger, IdempotencyKey
from utils import create_razorpay_order, get_razorpay_client, build_payu_params, payu_verify_response_hash
from webhook_handlers import webhooks_bp


def create_app() -> Flask:
    # Load environment variables from a .env file if present
    load_dotenv()
    app = Flask(__name__)
    app.config.from_object(Config)

    # Init DB
    db.init_app(app)
    with app.app_context():
        db.create_all()

    # Register blueprints
    app.register_blueprint(webhooks_bp)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "time": datetime.utcnow().isoformat()}

    @app.route("/", methods=["GET", "POST"])
    def index():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip()
            phone = request.form.get("phone", "").strip()
            consumer_id = request.form.get("consumer_id", "").strip()
            if not all([name, email, phone, consumer_id]):
                return render_template("index.html", error="All fields are required.")

            # Find or create user
            user = User.query.filter_by(email=email, consumer_id=consumer_id).first()
            if not user:
                user = User(name=name, email=email, phone=phone, consumer_id=consumer_id)
                db.session.add(user)
                db.session.commit()

            # Demo: compute a pseudo bill amount based on consumer id for determinism
            base = sum(ord(c) for c in consumer_id) % 400 + 100  # INR 100..499
            amount_paise = base * 100

            # Create our app order
            order_uuid = uuid.uuid4().hex
            order = Order(order_uuid=order_uuid, user_id=user.id, amount=amount_paise, status='CREATED')
            db.session.add(order)
            db.session.add(Ledger(order_id=None, entry_type='ORDER_CREATED', message=f"order_uuid={order_uuid}"))
            db.session.commit()

            return redirect(url_for('pay', order_uuid=order_uuid))

        # GET
        recent = Order.query.order_by(Order.created_at.desc()).limit(10).all()
        return render_template("index.html", recent_orders=recent)

    @app.post("/create_order")
    def create_order_route():
        data = request.get_json(silent=True) or {}
        order_uuid = data.get('order_uuid') or uuid.uuid4().hex
        amount_paise = int(data.get('amount_paise') or 10000)

        # Create a throwaway user if not provided (for API demo)
        user = None
        if data.get('email') and data.get('consumer_id'):
            user = User.query.filter_by(email=data['email'], consumer_id=data['consumer_id']).first()
            if not user:
                user = User(name=data.get('name') or 'Guest', email=data['email'], phone=data.get('phone') or '', consumer_id=data['consumer_id'])
                db.session.add(user)
                db.session.commit()
        else:
            user = User.query.first()
            if not user:
                user = User(name='Guest', email='guest@example.com', phone='9999999999', consumer_id='DEMO1234')
                db.session.add(user)
                db.session.commit()

        order = Order(order_uuid=order_uuid, user_id=user.id, amount=amount_paise, status='CREATED')
        db.session.add(order)
        db.session.commit()

        # Create Razorpay order now
        rzp_order = create_razorpay_order(amount_paise, receipt_id=order_uuid)
        order.razorpay_order_id = rzp_order.get('id')
        db.session.add(order)
        db.session.add(Ledger(order_id=order.id, entry_type='RZP_ORDER_ATTACHED', message=order.razorpay_order_id))
        db.session.commit()

        return jsonify({
            'order_uuid': order.order_uuid,
            'amount_paise': order.amount,
            'razorpay_order_id': order.razorpay_order_id,
            'razorpay_key_id': app.config['RAZORPAY_KEY_ID'],
        })

    @app.get("/pay/<order_uuid>")
    def pay(order_uuid: str):
        order = Order.query.filter_by(order_uuid=order_uuid).first()
        if not order:
            abort(404)
        user = order.user
        if app.config['PAYMENT_GATEWAY'] == 'payu':
            payu_params = build_payu_params(order, user)
            return render_template("pay.html", order=order, user=user, gateway='payu', payu_params=payu_params, PAYU_BASE_URL=app.config['PAYU_BASE_URL'])
        else:
            # Ensure Razorpay order exists
            error_msg = None
            if not order.razorpay_order_id:
                # Quick guard: if keys are defaults, avoid API call
                kid = app.config.get('RAZORPAY_KEY_ID') or ''
                ksec = app.config.get('RAZORPAY_KEY_SECRET') or ''
                looks_placeholder = (kid.startswith('rzp_test_x') and ksec in ('test_secret', '')) or (not kid or not ksec)
                if looks_placeholder:
                    error_msg = 'Razorpay credentials are not configured. Set RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET or switch PAYMENT_GATEWAY=payu.'
                else:
                    try:
                        rzp_order = create_razorpay_order(order.amount, receipt_id=order.order_uuid)
                        order.razorpay_order_id = rzp_order.get('id')
                        db.session.add(order)
                        db.session.add(Ledger(order_id=order.id, entry_type='RZP_ORDER_ATTACHED', message=order.razorpay_order_id))
                        db.session.commit()
                    except Exception as e:
                        error_msg = f"Razorpay order error: {str(e)}"

            return render_template(
                "pay.html",
                order=order,
                user=user,
                RAZORPAY_KEY_ID=app.config['RAZORPAY_KEY_ID'],
                gateway='razorpay',
                error=error_msg
            )

    @app.post("/verify_payment")
    def verify_payment():
        # This is the handler invoked after Checkout success on client.
        # We verify the signature synchronously and record the payment; capture is auto via order config.
        payload = request.get_json() or {}
        rzp_order_id = payload.get('razorpay_order_id')
        rzp_payment_id = payload.get('razorpay_payment_id')
        rzp_signature = payload.get('razorpay_signature')
        if not (rzp_order_id and rzp_payment_id and rzp_signature):
            return jsonify({'ok': False, 'error': 'Missing fields'}), 400

        client = get_razorpay_client()
        try:
            client.utility.verify_payment_signature({
                'razorpay_order_id': rzp_order_id,
                'razorpay_payment_id': rzp_payment_id,
                'razorpay_signature': rzp_signature,
            })
            verified = True
        except Exception as e:
            verified = False

        order = Order.query.filter_by(razorpay_order_id=rzp_order_id).first()
        if not order:
            return jsonify({'ok': False, 'error': 'Order not found'}), 404

        pay = Payment(order_id=order.id, payment_id=rzp_payment_id, method='razorpay', status='VERIFIED' if verified else 'FAILED')
        db.session.add(pay)
        if verified:
            order.status = 'RZP_SUCCESS'
            db.session.add(Ledger(order_id=order.id, entry_type='RZP_VERIFIED', message=rzp_payment_id))
        else:
            order.status = 'RZP_FAILED'
        db.session.add(order)
        db.session.commit()

        return jsonify({'ok': True, 'verified': verified, 'order_uuid': order.order_uuid})

    # --------------- Mobile: PayU create payment ---------------
    @app.post('/generatePayment')
    def generate_payment_mobile():
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        email = (data.get('email') or '').strip()
        phone = (data.get('phone') or '').strip()
        consumer_id = (data.get('consumer_id') or '').strip()
        amount_paise = int(data.get('amount_paise') or 0)
        bill_type = (data.get('bill_type') or 'maintenance').strip()
        if not all([name, email, phone, consumer_id, amount_paise]):
            return jsonify({'ok': False, 'error': 'Missing fields'}), 400

        user = User.query.filter_by(email=email, consumer_id=consumer_id).first()
        if not user:
            user = User(name=name, email=email, phone=phone, consumer_id=consumer_id)
            db.session.add(user)
            db.session.commit()

        order_uuid = uuid.uuid4().hex
        order = Order(order_uuid=order_uuid, user_id=user.id, amount=amount_paise, status='CREATED', bill_type=bill_type)
        db.session.add(order)
        db.session.add(Ledger(order_id=None, entry_type='ORDER_CREATED', message=f"order_uuid={order_uuid} amount={amount_paise}"))
        db.session.commit()

        payu_params = build_payu_params(order, user)
        return jsonify({'ok': True, 'gateway': 'payu', 'payu': payu_params, 'action': app.config['PAYU_BASE_URL'], 'order_uuid': order_uuid})

    # --------------- Mobile: PayU verify API ---------------
    @app.post('/payment/payu/verify')
    def payu_verify_api():
        data = request.get_json(silent=True) or {}
        ok = payu_verify_response_hash(data, app.config['PAYU_SALT'])
        order_uuid = data.get('txnid')
        order = Order.query.filter_by(order_uuid=order_uuid).first()
        if not order:
            return jsonify({'ok': False, 'error': 'Order not found'}), 404
        status = 'SUCCESS' if ok and (str(data.get('status')).lower() == 'success') else 'FAILED'
        payment_id = data.get('mihpayid') or 'payu_' + (data.get('txnid') or '')
        db.session.add(Payment(order_id=order.id, payment_id=payment_id, method='payu', status=status, amount=order.amount, bill_type=order.bill_type, webhook_payload=str(data)))
        order.status = 'PAID' if status == 'SUCCESS' else 'FAILED'
        db.session.add(order)
        db.session.add(Ledger(order_id=order.id, entry_type='PAYU_VERIFY', message=status))
        db.session.commit()
        return jsonify({'ok': True, 'status': order.status, 'order_uuid': order.order_uuid})
    # ---------------- PayU callbacks ----------------
    @app.post('/payment/payu/success')
    def payu_success():
        form = request.form.to_dict()  # PayU posts form data
        # Verify hash
        ok = payu_verify_response_hash(form, app.config['PAYU_SALT'])
        order_uuid = form.get('txnid')
        order = Order.query.filter_by(order_uuid=order_uuid).first()
        if not order:
            return abort(404)
        payment_id = form.get('mihpayid') or form.get('payuMoneyId') or 'payu_' + (form.get('txnid') or '')
        status = 'SUCCESS' if ok and (form.get('status') == 'success') else 'FAILED'
        db.session.add(Payment(order_id=order.id, payment_id=payment_id, method='payu', status=status, amount=order.amount, bill_type=order.bill_type, webhook_payload=str(form)))
        order.status = 'PAID' if status == 'SUCCESS' else 'FAILED'
        db.session.add(order)
        db.session.add(Ledger(order_id=order.id, entry_type='PAYU_RETURN', message=status))
        db.session.commit()
        return redirect(url_for('receipt', order_uuid=order.order_uuid))

    @app.post('/payment/payu/failure')
    def payu_failure():
        form = request.form.to_dict()
        order_uuid = form.get('txnid')
        order = Order.query.filter_by(order_uuid=order_uuid).first()
        if not order:
            return abort(404)
        payment_id = form.get('mihpayid') or 'payu_' + (form.get('txnid') or '')
        db.session.add(Payment(order_id=order.id, payment_id=payment_id, method='payu', status='FAILED', amount=order.amount, bill_type=order.bill_type, webhook_payload=str(form)))
        order.status = 'FAILED'
        db.session.add(order)
        db.session.add(Ledger(order_id=order.id, entry_type='PAYU_RETURN', message='FAILED'))
        db.session.commit()
        return redirect(url_for('receipt', order_uuid=order.order_uuid))

    @app.get("/receipt/<order_uuid>")
    def receipt(order_uuid: str):
        order = Order.query.filter_by(order_uuid=order_uuid).first_or_404()
        payment = Payment.query.filter_by(order_id=order.id).order_by(Payment.created_at.desc()).first()
        bbps = BBPSPayment.query.filter_by(order_id=order.id).order_by(BBPSPayment.created_at.desc()).first()
        return render_template("receipt.html", order=order, payment=payment, bbps=bbps)

    @app.get('/receipt/<order_uuid>/pdf')
    def receipt_pdf(order_uuid: str):
        # Minimal PDF for demo
        from io import BytesIO
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
        except Exception:
            return jsonify({'ok': False, 'error': 'reportlab not installed'}), 500

        order = Order.query.filter_by(order_uuid=order_uuid).first_or_404()
        payment = Payment.query.filter_by(order_id=order.id).order_by(Payment.created_at.desc()).first()
        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        text = c.beginText(40, 800)
        text.textLine('PGVCL BillPay Receipt')
        text.textLine(f'Order: {order.order_uuid}')
        text.textLine(f'Amount: ₹ {order.amount/100:.2f}')
        text.textLine(f'Status: {order.status}')
        text.textLine(f'Payment ID: {payment.payment_id if payment else "-"}')
        text.textLine(f'Time: {order.created_at}')
        c.drawText(text)
        c.showPage()
        c.save()
        pdf = buffer.getvalue()
        buffer.close()
        return (pdf, 200, {'Content-Type': 'application/pdf', 'Content-Disposition': f'inline; filename=receipt-{order_uuid}.pdf'})

    @app.get("/admin")
    def admin():
        orders = Order.query.order_by(Order.created_at.desc()).all()
        payments_by_order = {p.order_id: p for p in Payment.query.order_by(Payment.created_at.desc()).all()}
        bbps_by_order = {b.order_id: b for b in BBPSPayment.query.order_by(BBPSPayment.created_at.desc()).all()}
        ledger = Ledger.query.order_by(Ledger.created_at.desc()).limit(100).all()
        # Simple stats
        total_amount = sum(o.amount for o in orders)
        paid = sum(1 for o in orders if o.status in ('PAID', 'RZP_SUCCESS', 'RZP_CAPTURED'))
        failed = sum(1 for o in orders if 'FAILED' in (o.status or ''))
        pending = sum(1 for o in orders if o.status in ('CREATED', 'RZP_SUCCESS', 'BBPS_PENDING'))
        stats = {
            'orders': len(orders),
            'total_amount': total_amount,
            'paid': paid,
            'failed': failed,
            'pending': pending,
        }
        return render_template("admin.html", orders=orders, payments_by_order=payments_by_order, bbps_by_order=bbps_by_order, ledger=ledger, stats=stats)

    return app


app = create_app()

if __name__ == "__main__":
    # Dev server (Waitress recommended for Windows production)
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
