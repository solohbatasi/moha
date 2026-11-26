"""Passenger WSGI entry point that adapts the FastAPI ASGI app."""

import os
import sys

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from a2wsgi import ASGIMiddleware

from app.main import app as asgi_app

# Passenger expects a WSGI callable. ASGIMiddleware adapts the FastAPI ASGI app.
application = ASGIMiddleware(asgi_app)
