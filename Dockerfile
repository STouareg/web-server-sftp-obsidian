# --- builder: compilers + dev headers only here ---
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       libffi-dev \
       libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

RUN pip install --no-cache-dir -r requirements.txt

# --- runtime: no gcc; only libc SSL/FFI for wheels ---
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/venv/bin:$PATH" \
    TZ=Europe/Kyiv

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libffi8 \
       libssl3 \
       tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /venv /venv

WORKDIR /app
COPY app.py gunicorn.conf.py .

EXPOSE 8080

CMD ["gunicorn", "-c", "/app/gunicorn.conf.py", "app:app"]
