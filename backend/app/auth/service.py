"""Verifying a login. The only place a password is ever compared."""
from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from shared.database.passwords import hash_password, verify_password
from shared.database.schema import users

# Verified against when no such user exists, so a request for a missing account
# costs the same as one for a real account with the wrong password. Without it
# the response time alone tells an attacker which usernames are real.
_ABSENT = hash_password('there is no account with this name')


def authenticate(connection: Connection, username: str, password: str) -> str | None:
    """Return the username as stored, or None. Never says which half was wrong."""
    row = connection.execute(select(users.c.username, users.c.password_hash)
        .where(func.lower(users.c.username) == func.lower(username.strip()))).first()
    if row is None:
        verify_password(password, _ABSENT)
        return None
    return row.username if verify_password(password, row.password_hash) else None
