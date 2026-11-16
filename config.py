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
    # Optional engine tweaks (SSL for Postgres, connection health)
    SQLALCHEMY_ENGINE_OPTIONS = {}
    _db_url = str(SQLALCHEMY_DATABASE_URI)
    # Enable pre-ping to avoid stale connections in long-lived processes
    SQLALCHEMY_ENGINE_OPTIONS["pool_pre_ping"] = True
    # Allow forcing SSL mode via env for Postgres
    _sslmode = os.getenv("DATABASE_SSLMODE")
    if _db_url.startswith("postgresql://") and _sslmode:
        SQLALCHEMY_ENGINE_OPTIONS["connect_args"] = {"sslmode": _sslmode}

    # Razorpay credentials (set Sandbox or Production via env vars)
    RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID', '')
    RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET', '')
    RAZORPAY_WEBHOOK_SECRET = os.environ.get('RAZORPAY_WEBHOOK_SECRET', '')

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
