FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi==0.115.* uvicorn==0.32.* docker==7.* prometheus-client==0.21.*
WORKDIR /app
COPY control.py .
CMD ["uvicorn", "control:app", "--host", "0.0.0.0", "--port", "8090", "--log-level", "warning"]
