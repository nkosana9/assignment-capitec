FROM python:3.13-slim

# uv is copied in from its official image; the version matches the one used for uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN useradd --uid 10001 --no-create-home appuser

# Install locked runtime dependencies first so this layer is cached across code changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY version ./version
COPY service ./service

USER 10001
EXPOSE 8000

CMD ["uvicorn", "service.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
