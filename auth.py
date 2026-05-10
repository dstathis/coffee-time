"""
Authentication helpers for the Coffee Exchange app.

Two layers of auth:
  1. HTTP Basic Auth — protects the entire app with a shared
     username/password so only friends with the credentials can access it.
  2. Admin session auth — the /admin routes require an additional password
     entered via a login form, stored in the Flask session.

Credentials are read from environment variables:
  - APP_USERNAME, APP_PASSWORD  → Basic Auth
  - ADMIN_PASSWORD              → Admin login

See SPEC.md § Authentication for details.
"""

import os
from functools import wraps
from typing import Any, Callable

from flask import Response, redirect, request, session, url_for


def check_basic_auth(username: str, password: str) -> bool:
    """Validate Basic Auth credentials against environment variables."""
    expected_user = os.environ.get("APP_USERNAME", "")
    expected_pass = os.environ.get("APP_PASSWORD", "")
    if not expected_user or not expected_pass:
        raise RuntimeError(
            "APP_USERNAME and APP_PASSWORD environment variables must be set."
        )
    return username == expected_user and password == expected_pass


def require_basic_auth(f: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator that enforces HTTP Basic Auth on a route.

    Returns a 401 response with a WWW-Authenticate header if credentials
    are missing or invalid, prompting the browser's built-in login dialog.
    """

    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        auth = request.authorization
        if auth and check_basic_auth(auth.username, auth.password):
            return f(*args, **kwargs)
        return Response(
            "Authentication required.",
            401,
            {"WWW-Authenticate": 'Basic realm="Coffee Exchange"'},
        )

    return decorated


def check_admin_password(password: str) -> bool:
    """Validate the admin password against the environment variable."""
    expected = os.environ.get("ADMIN_PASSWORD", "")
    if not expected:
        raise RuntimeError(
            "ADMIN_PASSWORD environment variable must be set."
        )
    return password == expected


def require_admin(f: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator that enforces admin session auth on a route.

    Redirects to the admin login page if the session does not contain a
    valid admin flag.
    """

    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)

    return decorated
