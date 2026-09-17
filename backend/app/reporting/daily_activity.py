"""Compatibility import; reporting ownership lives outside the API package."""
from reporting.daily_activity import *  # noqa: F401,F403

if __name__ == "__main__":
    raise SystemExit(main())
