"""Sign in, sign out, and ask who is signed in.

The session is a signed cookie, so there is no server-side store to keep or
expire. It is HttpOnly, which keeps it out of reach of any script on the page,
and SameSite=Lax, so another site cannot ride it.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ..common.errors import ApiError
from ..database import DbConnection
from .schemas import Credentials, Session
from .service import authenticate

router = APIRouter(prefix='/auth', tags=['Authentication'])


def current_user(request: Request) -> str | None:
    return request.session.get('username')


def require_user(user: Annotated[str | None, Depends(current_user)]) -> str:
    """Every reporting route depends on this. Applied at the router, so a new
    endpoint is protected by being added rather than by remembering to."""
    if user is None:
        raise ApiError('not_authenticated', 'Sign in to read this.', 401)
    return user


@router.post('/login', response_model=Session)
def login(request: Request, connection: DbConnection, credentials: Credentials):
    """One message for a bad username and a bad password alike, so a caller
    cannot learn which usernames exist by comparing responses."""
    username = authenticate(connection, credentials.username, credentials.password)
    if username is None:
        raise ApiError('invalid_credentials', 'That username and password do not match.', 401)
    # A fresh session id on every login, so a cookie captured before signing in
    # cannot be reused afterwards.
    request.session.clear()
    request.session['username'] = username
    return dict(username=username)


@router.post('/logout', response_model=Session)
def logout(request: Request):
    request.session.clear()
    return dict(username=None)


@router.get('/session', response_model=Session)
def session(user: Annotated[str | None, Depends(current_user)]):
    """Lets the page find out whether it is signed in without guessing from a
    failed report request."""
    return dict(username=user)
