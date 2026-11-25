from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    created_at: Mapped[int] = mapped_column(BigInteger)


class EmailChallenge(Base):
    __tablename__ = "email_challenges"

    email: Mapped[str] = mapped_column(String(320), primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[int] = mapped_column(BigInteger)
    sent_at: Mapped[int] = mapped_column(BigInteger)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount_kes: Mapped[int] = mapped_column(Integer)
    phone: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="initiating", index=True)
    checkout_request_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    merchant_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mpesa_receipt: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    callback_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_query_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)
