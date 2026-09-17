# syntax=docker/dockerfile:1
FROM python:3.14-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY pyproject.toml ./
COPY api ./api
COPY common ./common
COPY data ./data
COPY domain ./domain
COPY reporting ./reporting
COPY seeding ./seeding
COPY app ./app
RUN python -m venv /opt/venv && /opt/venv/bin/python -m pip install .

FROM python:3.14-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd --gid 10001 aspire && useradd --uid 10001 --gid aspire --create-home aspire
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app/backend
USER aspire
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
