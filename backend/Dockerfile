FROM ghcr.io/astral-sh/uv:0.10.12@sha256:72ab0aeb448090480ccabb99fb5f52b0dc3c71923bffb5e2e26517a1c27b7fec AS uv
FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock /app/backend/
RUN cd backend && uv sync --frozen --no-dev --no-install-project
COPY backend /app/backend
COPY identity_provider /app/identity_provider
COPY specs/contracts /app/specs/contracts
RUN cd backend && uv sync --frozen --no-dev && useradd --uid 10001 --create-home scopegate \
    && mkdir -p /app/var/journal /app/var/mailbox /app/var/identity && chown -R scopegate:scopegate /app/var
ENV PATH="/app/backend/.venv/bin:$PATH" PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER scopegate
EXPOSE 8457
CMD ["uvicorn", "scopegate.main:app", "--host", "0.0.0.0", "--port", "8457", "--no-access-log"]
