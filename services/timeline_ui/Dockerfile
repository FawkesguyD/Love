FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV API_BASE_URL=
ENV CARDS_LIST_PATH=/api/cards
ENV CARD_BY_ID_PATH_TEMPLATE=/api/cards/{id}
ENV IMAGES_PATH=/api/images
ENV TIMER_PATH=/api/timer
ENV REQUEST_TIMEOUT_MS=6000
ENV CACHE_TTL_MS=45000
ENV MAX_MOMENTS=500
ENV BATCH_SIZE=16
ENV MAX_RETRIES=2
ENV TIMER_SYNC_INTERVAL_MS=60000
ENV HOST=0.0.0.0
ENV PORT=8010

EXPOSE 8010

CMD ["sh", "-c", "uvicorn app.main:app --host ${HOST} --port ${PORT}"]
