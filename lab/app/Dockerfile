FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi==0.115.* uvicorn==0.32.* redis==5.* "psycopg[binary]==3.2.*" prometheus-client==0.21.* httpx==0.27.*
RUN useradd -u 10001 -m app
WORKDIR /app
COPY app.py .
USER 10001
CMD ["python", "app.py"]
