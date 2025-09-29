# PGVCL Bill Payment (Flask + Razorpay + BBPS)

A minimal end-to-end demo to pay PGVCL electricity bills using Razorpay Checkout and a BBPS aggregator (stub).

## Features
- Landing page to enter consumer details
- Razorpay Orders + Checkout integration
- Webhook for Razorpay payment.captured
- Triggers BBPS bill payment (stub) after capture
- Receipt and Admin views
- SQLite via SQLAlchemy

## Setup

1. Create a Python virtual environment and install dependencies:

```
python -m venv .venv
.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
```

2. Set environment variables (Sandbox keys by default):

```
$env:SECRET_KEY = "change-me"
$env:RAZORPAY_KEY_ID = "rzp_test_xxxxx"
$env:RAZORPAY_KEY_SECRET = "your_test_secret"
$env:RAZORPAY_WEBHOOK_SECRET = "your_webhook_secret"  # from Razorpay dashboard webhook settings
# Optional BBPS aggregator demo
$env:BBPS_BASE_URL = "https://sandbox-bbps.example.com"
$env:BBPS_API_KEY = "demo-key"
$env:BILLER_CODE = "PGVCL"
# Payment Gateway (razorpay or payu)
$env:PAYMENT_GATEWAY = "payu"
$env:PAYU_MERCHANT_KEY = "your_key"
$env:PAYU_SALT = "your_salt"
$env:PAYU_BASE_URL = "https://test.payu.in/_payment"
$env:PAYU_SUCCESS_URL = "http://localhost:5000/payment/payu/success"
$env:PAYU_FAILURE_URL = "http://localhost:5000/payment/payu/failure"
```

3. Run the app:

```
python app.py
```

The app will be available at http://localhost:5000

## Webhooks
- Configure Razorpay webhook URL to: `http://<public-host>/webhook/razorpay` with event `payment.captured`.
- If your aggregator supports callbacks, set it to: `http://<public-host>/webhook/bbps`.

Use a tunneling tool during local dev (e.g., `cloudflared`, `ngrok`) to expose localhost.

## Notes
- BBPS integration is a stub. Replace `utils.trigger_bbps_billpay()` with your aggregator's API.
- Use the Admin page to view reconciliation data.
- For production, run with a proper WSGI server (e.g., Waitress on Windows) behind HTTPS.

```powershell
# Example production run (optional)
python -m waitress --listen=0.0.0.0:5000 app:app
```

## Deploy to Fly.io

Prereqs: Install Fly CLI and login.

```powershell
winget install flyctl
fly auth login
```

Initialize app (once), then deploy:

```powershell
fly launch --no-deploy  # uses provided fly.toml and Dockerfile
fly deploy
```

Set environment variables on Fly (replace with your secrets):

```powershell
fly secrets set SECRET_KEY=change-me
fly secrets set PAYMENT_GATEWAY=payu
fly secrets set PAYU_MERCHANT_KEY=your_key
fly secrets set PAYU_SALT=your_salt
fly secrets set PAYU_BASE_URL=https://secure.payu.in/_payment  # or test URL
fly secrets set PAYU_SUCCESS_URL=https://<your-app>.fly.dev/payment/payu/success
fly secrets set PAYU_FAILURE_URL=https://<your-app>.fly.dev/payment/payu/failure

# If also using Razorpay
fly secrets set RAZORPAY_KEY_ID=rzp_xxx
fly secrets set RAZORPAY_KEY_SECRET=xxx
fly secrets set RAZORPAY_WEBHOOK_SECRET=whsec_xxx

# Optional BBPS stub
fly secrets set BBPS_AGGREGATOR_ID=demo-aggregator
fly secrets set BBPS_API_KEY=demo-key
fly secrets set BBPS_BASE_URL=https://sandbox-bbps.example.com
fly secrets set BILLER_CODE=PGVCL
```

After deploy, your app is available at https://<your-app>.fly.dev

Health check is served at `/healthz`.
