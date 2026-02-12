FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV S3_ENDPOINT=http://s3:9000
ENV S3_ACCESS_KEY=dev
ENV S3_SECRET_KEY=devpassword
ENV S3_BUCKET=images
ENV S3_REGION=us-east-1
ENV S3_USE_SSL=false
ENV S3_FORCE_PATH_STYLE=true

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
