from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL

from common.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    database_url = settings.database_url
    if not database_url:
        if not all((settings.database_host, settings.database_name, settings.database_user,
                    settings.database_password)):
            raise RuntimeError("Configure DATABASE_URL or DATABASE_HOST, DATABASE_NAME, "
                               "DATABASE_USER and DATABASE_PASSWORD before accessing the database.")
        database_url = URL.create("postgresql+psycopg", username=settings.database_user,
                                  password=settings.database_password.get_secret_value(),
                                  host=settings.database_host, port=settings.database_port,
                                  database=settings.database_name)

    return create_engine(database_url, pool_pre_ping=True)

