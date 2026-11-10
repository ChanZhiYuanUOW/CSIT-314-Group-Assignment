from functools import wraps
from flask import session, g, redirect, url_for, abort
from entities import RegisteredUser


def current_manager():
    # Resolve the current CSV record rather than trusting a cached role in the cookie.
    user = RegisteredUser.findById(str(session.get('user_id', '')))
    if not user or user.get('status') != 'Active':
        return None
    return user


def manager_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_manager()
        if user is None:
            return redirect(url_for('auth.authenticateLogin'))
        if user['role'] != 'Platform Management':
            abort(403)
        g.pm_user = user
        return view(*args, **kwargs)
    return wrapped
