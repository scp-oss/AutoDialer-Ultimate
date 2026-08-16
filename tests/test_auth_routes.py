"""
Regression test for app/api/auth.py route registration.

AuthService.forgot_password()/confirm_forgot_password() were fully
implemented (reset token generation, Redis storage, password change) but
never wired up to any HTTP route - "forgot password" was unreachable
through the API entirely, on top of the token never being emailed to the
user (see app/utils/email.py). Verified live: POST /api/auth/forgot-password
-> /api/auth/reset-password -> login with the new password all worked
end-to-end once these routes were added.
"""

from app.api import auth


def test_forgot_password_and_reset_password_routes_are_registered():
    routes = {(frozenset(r.methods), r.path) for r in auth.router.routes}
    assert (frozenset({"POST"}), "/forgot-password") in routes
    assert (frozenset({"POST"}), "/reset-password") in routes
