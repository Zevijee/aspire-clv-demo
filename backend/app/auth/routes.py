"""Sign in, refresh, sign out, and ask who is signed in.

Two cookies, both HttpOnly so no script on the page can read them:

- `clearview_session`, the access cookie every report checks. Signed rather than
  stored, so checking it costs no query -- and for the same reason it cannot be
  revoked, which is why it is short-lived.
- `clearview_refresh`, a random token that renews it. Stored as a hash, so it can
  be revoked, and sent only to these routes, so no report request carries it.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from ..common.errors import ApiError, ErrorResponse
from ..database import DbWriteConnection
from .schemas import Credentials, Session
from .service import TokenReused, User, authenticate, revoke, rotate, start_family

router = APIRouter(prefix='/auth', tags=['Authentication'])

REFRESH_COOKIE = 'clearview_refresh'
REFRESH_PATH = '/api/v1/auth'
# token_urlsafe(32) is 43 characters. Anything much longer is not ours, and is
# refused before it is hashed or looked up.
MAX_TOKEN_LENGTH = 100


def current_user(request: Request) -> str | None:
    return request.session.get('username')


def require_user(user: Annotated[str | None, Depends(current_user)]) -> str:
    """Every reporting route depends on this. Applied at the router, so a new
    endpoint is protected by being added rather than by remembering to."""
    if user is None:
        raise ApiError('not_authenticated', 'Sign in to read this.', 401)
    return user


def _start_session(request: Request, user: User):
    # A fresh session on every sign-in and refresh, so a cookie captured before
    # cannot be reused afterwards, and the access period restarts.
    request.session.clear()
    request.session['username'] = user.username


def _set_refresh(request: Request, response: Response, token: str):
    settings = request.app.state.settings
    response.set_cookie(REFRESH_COOKIE, token, max_age=settings.refresh_days * 86400,
        path=REFRESH_PATH, httponly=True, secure=settings.session_https_only, samesite='strict')


def _clear_refresh(request: Request, response: Response):
    settings = request.app.state.settings
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, httponly=True,
        secure=settings.session_https_only, samesite='strict')


def _refresh_token(request: Request) -> str | None:
    token = request.cookies.get(REFRESH_COOKIE)
    return token if token and len(token) <= MAX_TOKEN_LENGTH else None


@router.post('/login', response_model=Session)
def login(request: Request, response: Response, connection: DbWriteConnection,
        credentials: Credentials):
    """One message for a bad username and a bad password alike, so a caller
    cannot learn which usernames exist by comparing responses."""
    user = authenticate(connection, credentials.username, credentials.password)
    if user is None:
        raise ApiError('invalid_credentials', 'That username and password do not match.', 401)
    token = start_family(connection, user, request.app.state.settings.refresh_days)
    _start_session(request, user)
    _set_refresh(request, response, token)
    return dict(username=user.username)


@router.post('/refresh', response_model=Session, responses={401: {'model': ErrorResponse}})
def refresh(request: Request, response: Response, connection: DbWriteConnection):
    """Renew the access cookie with the refresh token, and rotate the token.

    A 401 means sign in again. The error is returned rather than raised, because
    raising would roll back the transaction -- and a reused token's family must
    stay revoked.
    """
    token = _refresh_token(request)
    try:
        refreshed = rotate(connection, token, request.app.state.settings.refresh_days) if token else None
    except TokenReused:
        refreshed = None
    if refreshed is None:
        request.session.clear()
        failure = JSONResponse(status_code=401, content=dict(code='not_authenticated',
            detail='Your session has ended. Sign in again.'))
        _clear_refresh(request, failure)
        return failure
    _start_session(request, refreshed.user)
    if refreshed.token is not None:
        _set_refresh(request, response, refreshed.token)
    return dict(username=refreshed.user.username)


@router.post('/logout', response_model=Session)
def logout(request: Request, response: Response, connection: DbWriteConnection):
    """Revokes the refresh token server-side, so a copy of it stops working too.
    The access cookie cannot be revoked; it lapses within minutes."""
    token = _refresh_token(request)
    if token:
        revoke(connection, token)
    request.session.clear()
    _clear_refresh(request, response)
    return dict(username=None)


@router.get('/session', response_model=Session)
def session(user: Annotated[str | None, Depends(current_user)]):
    """Lets the page find out whether it is signed in without guessing from a
    failed report request. Null does not mean signed out: the access cookie may
    simply have lapsed, and refresh may still renew it."""
    return dict(username=user)
