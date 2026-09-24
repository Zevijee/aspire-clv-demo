"""The one account permitted to read the reports.

Run: python manage.py admin_user --regenerate
Needs ADMIN_PASSWORD in the environment, or in the root .env beside DATABASE_URL.

The password is read from the environment and never written anywhere but as a
bcrypt digest. It is deliberately not defaulted: a fallback password in a
repository is the same as no password, because it ships to every clone and every
deploy, and nobody changes it. Running without the variable fails and says so.

Rerunning with a different password updates the stored digest, which is how the
password is rotated -- there is no separate command for it. It also revokes every
refresh token, so everyone signed in has to sign in again.
"""
from datetime import datetime, timezone
import os

from base import BaseGenerator
from shared.database.passwords import hash_password
from shared.database.schema import refresh_tokens

USERNAME = 'admin'


class AdminUserGenerator(BaseGenerator):
    name = 'admin_user'
    table = BaseGenerator.users

    def can_reuse(self, connection, counts):
        """Never reuse.

        Every other reference generator skips when its rows are already there,
        because its output is a pure function of a JSON file. This one's output
        depends on an environment variable that the saved row cannot be compared
        against -- a bcrypt digest is not reversible, and hashing again produces
        a different string because the salt is new. So it always rewrites, which
        is also what makes rerunning it the way to change the password.
        """
        return False

    def prepare_sources(self, connection):
        self._password = os.getenv('ADMIN_PASSWORD', '').strip()
        if not self._password:
            raise ValueError(
                'Set ADMIN_PASSWORD before seeding the admin user. Put it in the root .env '
                'for local work, or in the service environment file on a server. It is not '
                'defaulted on purpose: a password committed to a repository protects nothing.')
        # A new password ends every existing sign-in, in the same transaction as
        # the new digest. Otherwise a stolen refresh token would outlive the
        # password it was issued under.
        connection.execute(refresh_tokens.delete())

    def expected_rows(self):
        return 1

    def generate(self):
        return [dict(
            # Derived from the username, so reseeding updates the existing row
            # rather than accumulating a second admin every time.
            user_id=self.source_id('user', USERNAME),
            username=USERNAME,
            password_hash=hash_password(self._password),
            # Supplied rather than left to the column default: the writer sends
            # whole rows, so every declared column has to be present.
            created_at=datetime.now(timezone.utc),
        )]


GENERATORS = (AdminUserGenerator,)
