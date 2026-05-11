FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       libffi-dev \
       libssl-dev \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y build-essential libffi-dev libssl-dev \
    && apt-get install -y --no-install-recommends libffi8 libssl3 \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY app.py gunicorn.conf.py .

EXPOSE 8080

CMD ["gunicorn", "-c", "/app/gunicorn.conf.py", "app:app"]
