import smtplib
from email.message import EmailMessage

from .config import env, required


def send_login_code(recipient: str, code: str) -> None:
    host = required("SMTP_HOST")
    username = required("SMTP_USERNAME")
    password = required("SMTP_PASSWORD")
    sender = required("SMTP_FROM_EMAIL")
    port = int(env("SMTP_PORT", "587"))
    message = EmailMessage()
    message["Subject"] = "Your Codility Pro 254 sign-in code"
    message["From"] = f'{env("SMTP_FROM_NAME", "Codility Pro 254")} <{sender}>'
    message["To"] = recipient
    message.set_content(f"Your sign-in code is {code}. It expires in 10 minutes. If you did not request it, ignore this email.")

    if env("SMTP_USE_TLS", "true").lower() == "true":
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP_SSL(host, port, timeout=20) as smtp:
            smtp.login(username, password)
            smtp.send_message(message)
