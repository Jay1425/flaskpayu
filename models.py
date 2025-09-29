from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

# Create the SQLAlchemy db instance (initialized in app.py)
db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    consumer_id = db.Column(db.String(50), index=True, nullable=False)

    orders = db.relationship('Order', backref='user', lazy=True)

class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    order_uuid = db.Column(db.String(64), unique=True, index=True)  # our app order id
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    bill_type = db.Column(db.String(50), default='electricity', index=True)
    amount = db.Column(db.Integer, nullable=False)  # in paise
    status = db.Column(db.String(50), default='CREATED', index=True)
    razorpay_order_id = db.Column(db.String(100), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    payments = db.relationship('Payment', backref='order', lazy=True)
    bbps_payments = db.relationship('BBPSPayment', backref='order', lazy=True)

class Payment(db.Model):
    __tablename__ = 'payments'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    payment_id = db.Column(db.String(100), index=True)  # razorpay_payment_id
    method = db.Column(db.String(50))
    bill_type = db.Column(db.String(50), index=True)
    status = db.Column(db.String(50), index=True)
    amount = db.Column(db.Integer)
    webhook_payload = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class BBPSPayment(db.Model):
    __tablename__ = 'bbps_payments'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    bbps_txn_id = db.Column(db.String(100), index=True)
    request_id = db.Column(db.String(100), index=True)
    status = db.Column(db.String(50), index=True)
    response_payload = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Ledger(db.Model):
    __tablename__ = 'ledger'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, index=True)
    entry_type = db.Column(db.String(50))  # ORDER_CREATED, RZP_CAPTURED, BBPS_TRIGGERED, BBPS_CONFIRMED, etc
    message = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class IdempotencyKey(db.Model):
    __tablename__ = 'idempotency_keys'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, index=True)
    used_at = db.Column(db.DateTime, default=datetime.utcnow)
