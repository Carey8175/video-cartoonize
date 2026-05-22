FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY video_cartoonize ./video_cartoonize

RUN pip install --no-cache-dir ".[server]"

EXPOSE 7317

CMD ["cartoonize", "serve", "--host", "0.0.0.0", "--port", "7317"]
