"""Verifying a login, and issuing, rotating and revoking refresh tokens.

The only place a password is ever compared, and the only code in the API that
writes to the database.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from shared.database.passwords import hash_password, verify_password
from shared.database.schema import refresh_tokens as tokens, users

# Verified against when no such user exists, so a request for a missing account
# costs the same as one for a real account with the wrong password. Without it
# the response time alone tells an attacker which usernames are real.
_ABSENT = hash_password('there is no account with this name')

# Two tabs whose access cookies expire together both refresh with the same token.
# The first rotates it; the second arrives moments later with the old one. That
# is not theft -- the browser already holds the replacement, because cookies are
# shared between tabs -- so a use this soon after rotation renews access without
# rotating again. Any later reuse revokes the family.
ROTATION_GRACE = timedelta(seconds=30)


@dataclass(frozen=True)
class User:
    user_id: UUID
    username: str


@dataclass(frozen=True)
class Refreshed:
    user: User
    # None inside the rotation grace: the browser already has the current token.
    token: str | None


class TokenReused(Exception):
    """A replaced token was presented again. Its family has been revoked."""


def authenticate(connection: Connection, username: str, password: str) -> User | None:
    """Return the user as stored, or None. Never says which half was wrong."""
    row = connection.execute(select(users.c.user_id, users.c.username, users.c.password_hash)
        .where(func.lower(users.c.username) == func.lower(username.strip()))).first()
    if row is None:
        verify_password(password, _ABSENT)
        return None
    return User(row.user_id, row.username) if verify_password(password, row.password_hash) else None


def _digest(token: str) -> str:
    return sha256(token.encode('utf-8')).hexdigest()


def _issue(connection: Connection, user_id: UUID, family_id: UUID, now: datetime, days: int) -> str:
    token = token_urlsafe(32)
    connection.execute(tokens.insert().values(token_hash=_digest(token), family_id=family_id,
        user_id=user_id, issued_at=now, expires_at=now + timedelta(days=days)))
    return token


def start_family(connection: Connection, user: User, days: int) -> str:
    """A new sign-in. Also sweeps expired rows, so the table never needs a job."""
    now = datetime.now(timezone.utc)
    connection.execute(tokens.delete().where(tokens.c.expires_at < now))
    return _issue(connection, user.user_id, uuid4(), now, days)


def rotate(connection: Connection, token: str, days: int) -> Refreshed | None:
    """Exchange a refresh token for its successor.

    None for an unknown, expired or revoked token. Raises TokenReused, after
    revoking the family, for a replaced token presented outside the grace period.
    The row is locked so two concurrent refreshes are applied one after the other.
    """
    now = datetime.now(timezone.utc)
    row = connection.execute(select(tokens, users.c.username)
        .join(users, users.c.user_id == tokens.c.user_id)
        .where(tokens.c.token_hash == _digest(token))
        .with_for_update(of=tokens)).mappings().first()
    if row is None or row['revoked_at'] is not None or row['expires_at'] <= now:
        return None
    user = User(row['user_id'], row['username'])
    if row['replaced_at'] is not None:
        if now - row['replaced_at'] <= ROTATION_GRACE:
            return Refreshed(user, None)
        revoke_family(connection, row['family_id'])
        raise TokenReused()
    connection.execute(tokens.update().where(tokens.c.token_hash == row['token_hash'])
        .values(replaced_at=now))
    return Refreshed(user, _issue(connection, row['user_id'], row['family_id'], now, days))


def revoke_family(connection: Connection, family_id: UUID):
    connection.execute(tokens.update().where(tokens.c.family_id == family_id,
        tokens.c.revoked_at.is_(None)).values(revoked_at=datetime.now(timezone.utc)))


def revoke(connection: Connection, token: str):
    """Sign-out. Ends every token descended from this sign-in, not only this one."""
    family_id = connection.scalar(select(tokens.c.family_id)
        .where(tokens.c.token_hash == _digest(token)))
    if family_id is not None:
        revoke_family(connection, family_id)
