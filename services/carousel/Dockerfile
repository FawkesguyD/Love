FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV S3_ENDPOINT=
ENV S3_ACCESS_KEY=
ENV S3_SECRET_KEY=
ENV S3_BUCKET=
ENV S3_REGION=us-east-1
ENV S3_USE_SSL=false
ENV S3_FORCE_PATH_STYLE=true
ENV HOST=0.0.0.0
ENV PORT=8001

EXPOSE 8001

CMD ["sh", "-c", "uvicorn app.main:app --host ${HOST} --port ${PORT}"]
