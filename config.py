import os

class Config:
    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

    # Database: default to SQLite in local folder
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(os.path.dirname(__file__), 'app.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Razorpay credentials (set Sandbox or Production via env vars)
    RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "rzp_test_xxxxxxxx")
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "test_secret")
    RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "test_webhook_secret")

    # BBPS aggregator credentials
    BBPS_AGGREGATOR_ID = os.getenv("BBPS_AGGREGATOR_ID", "demo-aggregator")
    BBPS_API_KEY = os.getenv("BBPS_API_KEY", "demo-bbps-key")
    BBPS_BASE_URL = os.getenv("BBPS_BASE_URL", "https://sandbox-bbps.example.com")

    # App specifics
    BILLER_CODE = os.getenv("BILLER_CODE", "PGVCL")

    # Payment gateway selection: 'razorpay' (default) or 'payu'
    PAYMENT_GATEWAY = os.getenv("PAYMENT_GATEWAY", "razorpay").lower()

    # PayU configuration
    PAYU_MERCHANT_KEY = os.getenv("PAYU_MERCHANT_KEY", "test_key")
    PAYU_SALT = os.getenv("PAYU_SALT", "test_salt")
    # Example: https://test.payu.in/_payment for sandbox, https://secure.payu.in/_payment for prod
    PAYU_BASE_URL = os.getenv("PAYU_BASE_URL", "https://test.payu.in/_payment")
    # Callback URLs (should be public URLs in production)
    PAYU_SUCCESS_URL = os.getenv("PAYU_SUCCESS_URL", "http://localhost:5000/payment/payu/success")
    PAYU_FAILURE_URL = os.getenv("PAYU_FAILURE_URL", "http://localhost:5000/payment/payu/failure")
