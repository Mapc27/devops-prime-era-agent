FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl postgresql-client redis-tools iproute2 procps dnsutils iputils-ping \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir fastapi==0.115.* uvicorn==0.32.*
RUN useradd -u 10002 -m sandbox
WORKDIR /app
COPY executor.py .
USER 10002
CMD ["uvicorn", "executor:app", "--host", "0.0.0.0", "--port", "8091", "--log-level", "warning"]
