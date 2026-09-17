"""Compatibility import; implementation lives in seeding.__main__."""
from seeding.__main__ import *  # noqa: F401,F403

if __name__ == '__main__':
    raise SystemExit(main())
