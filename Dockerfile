FROM python:3.13-slim

WORKDIR /app

COPY server/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY server/ ./server/
COPY shared/ ./shared/
COPY migrations/ ./migrations/

EXPOSE 12345

CMD ["python", "-m", "server", "-H", "0.0.0.0"]
