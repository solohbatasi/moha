import base64
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from .config import MPESA_ENV, MPESA_TIMEOUT_SECONDS, required


def base_url() -> str:
    if MPESA_ENV == "sandbox":
        return "https://sandbox.safaricom.co.ke"
    if MPESA_ENV == "production":
        return "https://api.safaricom.co.ke"
    raise RuntimeError("MPESA_ENV must be 'sandbox' or 'production'")


def _token() -> str:
    key = required("MPESA_CONSUMER_KEY")
    secret = required("MPESA_CONSUMER_SECRET")
    response = requests.get(f"{base_url()}/oauth/v1/generate?grant_type=client_credentials",
                            auth=(key, secret), timeout=MPESA_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()["access_token"]


def _stk_password(shortcode: str, passkey: str, timestamp: str) -> str:
    raw = f"{shortcode}{passkey}{timestamp}".encode()
    return base64.b64encode(raw).decode()


def start_buygoods_push(phone: str, amount: int, reference: str) -> dict:
    shortcode = required("MPESA_BUSINESS_SHORTCODE")
    till = required("MPESA_TILL_NUMBER")
    passkey = required("MPESA_PASSKEY")
    callback = required("MPESA_CALLBACK_URL")
    timestamp = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y%m%d%H%M%S")
    body = {
        "BusinessShortCode": shortcode,
        "Password": _stk_password(shortcode, passkey, timestamp),
        "Timestamp": timestamp,
        "TransactionType": "CustomerBuyGoodsOnline",
        "Amount": amount,
        "PartyA": phone,
        "PartyB": till,
        "PhoneNumber": phone,
        "CallBackURL": callback,
        "AccountReference": reference[:12],
        "TransactionDesc": "AppAccess",
    }
    response = requests.post(f"{base_url()}/mpesa/stkpush/v1/processrequest", json=body,
                             headers={"Authorization": f"Bearer {_token()}"},
                             timeout=MPESA_TIMEOUT_SECONDS)
    response.raise_for_status()
    data = response.json()
    if data.get("ResponseCode") != "0" or not data.get("CheckoutRequestID"):
        raise RuntimeError(data.get("errorMessage") or data.get("ResponseDescription") or "Daraja rejected the STK Push")
    return data


def query_stk(checkout_request_id: str) -> dict:
    shortcode = required("MPESA_BUSINESS_SHORTCODE")
    passkey = required("MPESA_PASSKEY")
    timestamp = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y%m%d%H%M%S")
    body = {
        "BusinessShortCode": shortcode,
        "Password": _stk_password(shortcode, passkey, timestamp),
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_request_id,
    }
    response = requests.post(f"{base_url()}/mpesa/stkpushquery/v1/query", json=body,
                             headers={"Authorization": f"Bearer {_token()}"},
                             timeout=MPESA_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()
