FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/venv PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY opscrew ./opscrew
COPY config ./config
RUN uv sync --frozen --no-dev && useradd -u 10003 -m agent && mkdir -p /data && chown agent /data
USER 10003
EXPOSE 8080
CMD ["python", "-m", "opscrew.api"]
