"""Password hashing, shared by the seeder that writes a user and the API that
checks one. Both sides must agree on the algorithm, so it lives in one place.

bcrypt rather than a bare digest: it is deliberately slow and salts each hash,
so two accounts with the same password do not produce the same row and an
offline attacker cannot test candidates cheaply. The salt and cost factor travel
inside the hash string, which is why raising COST later needs no schema change
and no migration -- existing hashes keep verifying at the cost they were made
with.
"""
import bcrypt

# Roughly 100ms per verification on the demo server. High enough to make guessing
# expensive, low enough that a login does not feel broken.
COST = 12
# bcrypt silently truncates at 72 bytes, so a longer password would have its tail
# ignored. Refusing is honest; accepting and ignoring part of it is not.
MAX_BYTES = 72


def hash_password(password: str) -> str:
    encoded = password.encode('utf-8')
    if len(encoded) > MAX_BYTES:
        raise ValueError(f'Passwords are limited to {MAX_BYTES} bytes; bcrypt ignores the rest.')
    if not password.strip():
        raise ValueError('A password cannot be blank.')
    return bcrypt.hashpw(encoded, bcrypt.gensalt(COST)).decode('ascii')


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time comparison, and never raises on a malformed stored hash."""
    try:
        encoded = password.encode('utf-8')
        if len(encoded) > MAX_BYTES:
            return False
        return bcrypt.checkpw(encoded, password_hash.encode('ascii'))
    except (ValueError, TypeError):
        return False
