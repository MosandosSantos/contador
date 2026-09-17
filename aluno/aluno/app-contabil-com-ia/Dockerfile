FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production PORT=5000
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home appuser
COPY app.py .
COPY config/ config/
COPY core/ core/
COPY modules/ modules/
COPY templates/ templates/
COPY static/ static/
COPY dados/ dados/
COPY scripts/schema.sql scripts/schema.sql
COPY scripts/preparar.py scripts/preparar.py
USER appuser
EXPOSE 5000
CMD ["sh", "-c", "python scripts/preparar.py && exec gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 2 --threads 2 --timeout 60 app:app"]
