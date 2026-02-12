FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV MONGO_URI=mongodb://mongo:27017
ENV MONGO_DB_NAME=app
ENV PHOTOSTOCK_BASE_URL=http://photostock:8000
ENV PHOTOSTOCK_TIMEOUT_MS=2000
ENV HOST=0.0.0.0
ENV PORT=8002

EXPOSE 8002

CMD ["sh", "-c", "uvicorn app.main:app --host ${HOST} --port ${PORT}"]
