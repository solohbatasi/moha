import hashlib
import hmac
import secrets
import time

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import (JWT_SECRET, TEST_ACCESS_TOKEN, TEST_MODE,
                     TEST_USER_EMAIL)
from .db import get_db
from .models import User

bearer = HTTPBearer(auto_error=False)


def check_secret() -> None:
    if len(JWT_SECRET) < 32 or "replace-with" in JWT_SECRET.lower():
        raise RuntimeError("Set JWT_SECRET to a random value of at least 32 characters")


def otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def otp_digest(email: str, code: str) -> str:
    return hmac.new(JWT_SECRET.encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def issue_token(user: User) -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(user.id), "email": user.email, "iat": now,
                       "exp": now + 60 * 60 * 24 * 30}, JWT_SECRET, algorithm="HS256")


def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Sign-in required")
    if credentials.credentials == TEST_ACCESS_TOKEN:
        if (not TEST_MODE or request.client is None or
                request.client.host not in {"127.0.0.1", "::1", "localhost"}):
            raise HTTPException(status_code=401, detail="Invalid or expired access token")
        user = db.scalar(select(User).where(User.email == TEST_USER_EMAIL))
        if user is None:
            raise HTTPException(status_code=401, detail="Test sign-in required")
        return user
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired access token")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Account not found")
    return user
