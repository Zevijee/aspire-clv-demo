# syntax=docker/dockerfile:1

# The API and the seeder both import shared.database, so this builds from the
# repository root rather than from backend/. One image runs either of them; which
# one is a command, not a separate build.

FROM python:3.13-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
# Requirements first: dependency layers survive source edits.
COPY shared/database/requirements.txt shared/database/requirements.txt
COPY backend/requirements.txt backend/requirements.txt
COPY sandbox-data/requirements.txt sandbox-data/requirements.txt
RUN python -m venv /opt/venv && /opt/venv/bin/python -m pip install \
        -r backend/requirements.txt -r sandbox-data/requirements.txt

FROM python:3.13-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd --gid 10001 aspire && useradd --uid 10001 --gid aspire --create-home aspire
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=aspire:aspire pyproject.toml ./
COPY --chown=aspire:aspire shared ./shared
COPY --chown=aspire:aspire backend ./backend
COPY --chown=aspire:aspire sandbox-data ./sandbox-data
USER aspire
EXPOSE 8000
# Containers must bind every interface; the local default stays 127.0.0.1.
CMD ["python", "backend/manage.py", "serve", "--host", "0.0.0.0"]
