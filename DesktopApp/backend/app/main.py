import json
import logging
import secrets
import time
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import (APP_ENV, APP_PRICE_KES, OTP_MAX_ATTEMPTS,
                     OTP_RESEND_SECONDS, OTP_TTL_SECONDS, TEST_ACCESS_TOKEN,
                     TEST_MODE, TEST_PASSWORD, TEST_USER_EMAIL, env)
from .daraja import query_stk, start_buygoods_push
from .db import Base, engine, get_db
from .email_service import send_login_code
from .models import EmailChallenge, Payment, User
from .security import check_secret, current_user, issue_token, otp_code, otp_digest

Base.metadata.create_all(bind=engine)
check_secret()

app = FastAPI(title="Codility Pro 254 Backend", version="1.0.0")
origins = [origin.strip() for origin in env("CLIENT_ORIGINS", "*").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins or ["*"],
                   allow_credentials=False, allow_methods=["GET", "POST"],
                   allow_headers=["Authorization", "Content-Type"])


class EmailRequest(BaseModel):
    email: EmailStr


class EmailVerify(EmailRequest):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class TestLogin(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class PaymentRequest(BaseModel):
    phone: str = Field(min_length=9, max_length=16)


def has_access(db: Session, user_id: int) -> bool:
    if TEST_MODE:
        user = db.get(User, user_id)
        if user is not None and user.email == TEST_USER_EMAIL:
            return True
    return db.scalar(select(Payment.id).where(Payment.user_id == user_id,
                                               Payment.status == "paid").limit(1)) is not None


def normalize_email(value: str) -> str:
    return value.strip().lower()


def normalize_phone(value: str) -> str:
    digits = "".join(char for char in value if char.isdigit())
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif digits.startswith("254") and len(digits) == 12:
        pass
    elif digits.startswith("7") or digits.startswith("1"):
        if len(digits) == 9:
            digits = "254" + digits
    if len(digits) != 12 or not digits.startswith(("2547", "2541")):
        raise HTTPException(status_code=422, detail="Enter a valid Kenyan M-Pesa number")
    return digits


@app.get("/health")
def health():
    return {"status": "ok", "environment": APP_ENV}


@app.post("/api/auth/email/request")
def request_email_code(payload: EmailRequest, db: Session = Depends(get_db)):
    email = normalize_email(str(payload.email))
    now = int(time.time())
    challenge = db.get(EmailChallenge, email)
    if challenge and now - challenge.sent_at < OTP_RESEND_SECONDS:
        raise HTTPException(status_code=429, detail="Please wait before requesting another code")
    code = otp_code()
    if challenge is None:
        challenge = EmailChallenge(email=email, code_hash=otp_digest(email, code),
                                   expires_at=now + OTP_TTL_SECONDS, sent_at=now, attempts=0)
        db.add(challenge)
    else:
        challenge.code_hash = otp_digest(email, code)
        challenge.expires_at = now + OTP_TTL_SECONDS
        challenge.sent_at = now
        challenge.attempts = 0
    db.commit()
    try:
        send_login_code(email, code)
    except Exception as exc:
        db.delete(challenge)
        db.commit()
        # Do not return SMTP credentials or server details to the client.
        logging.getLogger(__name__).exception("Unable to send sign-in code")
        raise HTTPException(status_code=503, detail="Email delivery is temporarily unavailable") from exc
    return {"success": True, "message": "If the address can receive mail, a sign-in code has been sent."}


@app.post("/api/auth/test-login")
def test_login(payload: TestLogin, request: Request, db: Session = Depends(get_db)):
    if (not TEST_MODE or request.client is None or
            request.client.host not in {"127.0.0.1", "::1", "localhost"}):
        raise HTTPException(status_code=404, detail="Not found")
    if not secrets.compare_digest(payload.password, TEST_PASSWORD):
        raise HTTPException(status_code=401, detail="Invalid test password")
    user = db.scalar(select(User).where(User.email == TEST_USER_EMAIL))
    if user is None:
        user = User(email=TEST_USER_EMAIL, created_at=int(time.time()))
        db.add(user)
        db.commit()
    return {"success": True, "access_token": TEST_ACCESS_TOKEN,
            "token_type": "bearer", "email": TEST_USER_EMAIL,
            "has_access": True, "test_mode": True}


@app.post("/api/auth/email/verify")
def verify_email_code(payload: EmailVerify, db: Session = Depends(get_db)):
    email = normalize_email(str(payload.email))
    challenge = db.get(EmailChallenge, email)
    now = int(time.time())
    if challenge is None or challenge.expires_at < now or challenge.attempts >= OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=401, detail="Code is invalid or expired")
    if not secrets.compare_digest(challenge.code_hash, otp_digest(email, payload.code)):
        challenge.attempts += 1
        db.commit()
        raise HTTPException(status_code=401, detail="Code is invalid or expired")
    db.delete(challenge)
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, created_at=now)
        db.add(user)
        db.flush()
    db.commit()
    return {"success": True, "access_token": issue_token(user), "token_type": "bearer",
            "email": user.email, "has_access": has_access(db, user.id)}


@app.get("/api/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"email": user.email, "has_access": has_access(db, user.id)}


@app.post("/api/payments/stk-push")
def create_payment(payload: PaymentRequest, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    if has_access(db, user.id):
        return {"success": True, "status": "paid", "has_access": True}
    if APP_PRICE_KES <= 0:
        raise HTTPException(status_code=503, detail="Payment amount is not configured")
    phone = normalize_phone(payload.phone)
    now = int(time.time())
    payment_id = secrets.token_hex(12)
    payment = Payment(id=payment_id, user_id=user.id, amount_kes=APP_PRICE_KES,
                      phone=phone, status="initiating", created_at=now, updated_at=now)
    db.add(payment)
    db.commit()
    try:
        response = start_buygoods_push(phone, APP_PRICE_KES, f"APP{payment_id[:8]}")
    except Exception as exc:
        payment.status = "failed"
        payment.updated_at = int(time.time())
        db.commit()
        raise HTTPException(status_code=502, detail="Could not start the M-Pesa payment. Check configuration and try again.") from exc
    payment.status = "pending"
    payment.checkout_request_id = response["CheckoutRequestID"]
    payment.merchant_request_id = response.get("MerchantRequestID")
    payment.updated_at = int(time.time())
    db.commit()
    return {"success": True, "payment_id": payment.id, "status": payment.status,
            "amount_kes": payment.amount_kes,
            "message": response.get("CustomerMessage", "Check your phone to complete the payment")}


@app.get("/api/payments/{payment_id}")
def get_payment(payment_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    payment = db.get(Payment, payment_id)
    if payment is None or payment.user_id != user.id:
        raise HTTPException(status_code=404, detail="Payment not found")
    if (payment.status == "pending" and payment.callback_json and
            (payment.last_query_at is None or int(time.time()) - payment.last_query_at >= 20)):
        process_mpesa_result(payment, json.loads(payment.callback_json), db)
    return {"payment_id": payment.id, "status": payment.status,
            "amount_kes": payment.amount_kes, "has_access": has_access(db, user.id)}


def callback_values(payload: dict[str, Any]) -> tuple[str | None, str | None, dict[str, Any]]:
    body = payload.get("Body", {}).get("stkCallback", {})
    checkout_id = body.get("CheckoutRequestID")
    result_code = str(body.get("ResultCode")) if body.get("ResultCode") is not None else None
    metadata: dict[str, Any] = {}
    for item in body.get("CallbackMetadata", {}).get("Item", []):
        if isinstance(item, dict) and "Name" in item:
            metadata[item["Name"]] = item.get("Value")
    return checkout_id, result_code, metadata


def process_mpesa_result(payment: Payment, payload: dict[str, Any], db: Session) -> None:
    checkout_id, result_code, metadata = callback_values(payload)
    payment.callback_json = json.dumps(payload, separators=(",", ":"))[:8000]
    payment.result_code = result_code
    payment.updated_at = int(time.time())
    if result_code != "0":
        payment.status = "failed"
        db.commit()
        return

    # Treat the callback as a notification. Confirm the checkout directly with Daraja,
    # and compare the amount and payer before granting the permanent entitlement.
    payment.last_query_at = int(time.time())
    db.commit()
    try:
        confirmation = query_stk(checkout_id or "")
    except Exception:
        # Keep it pending; the authenticated status endpoint retries the query later.
        return
    query_code = str(confirmation.get("ResultCode")) if confirmation.get("ResultCode") is not None else None
    try:
        callback_amount = int(float(metadata.get("Amount")))
        callback_phone = str(int(metadata.get("PhoneNumber")))
    except (TypeError, ValueError):
        callback_amount, callback_phone = -1, ""
    if query_code == "0" and callback_amount == payment.amount_kes and callback_phone == payment.phone:
        payment.status = "paid"
        payment.mpesa_receipt = str(metadata.get("MpesaReceiptNumber", ""))[:32] or None
    else:
        payment.status = "failed"
        payment.result_code = query_code or result_code
    payment.updated_at = int(time.time())
    db.commit()


@app.post("/api/payments/mpesa/callback")
async def mpesa_callback(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        return {"Result": "Accepted"}
    checkout_id, result_code, metadata = callback_values(payload)
    if not checkout_id:
        return {"Result": "Accepted"}
    payment = db.scalar(select(Payment).where(Payment.checkout_request_id == checkout_id))
    if payment is None or payment.status == "paid":
        return {"Result": "Accepted"}
    process_mpesa_result(payment, payload, db)
    return {"Result": "Accepted"}
