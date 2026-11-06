# Adsify backend: FastAPI + Playwright Firefox + FFmpeg.   Build:  docker build -t adsify-backend ./backend
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DATA_DIR=/data \
    DATABASE_URL=sqlite:////data/adsify.db \
    APP_ENV=production

# FFmpeg makes every video; the fonts draw the name / phone / address on the video (Latin, Devanagari, Arabic, Tamil).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core fonts-noto-core curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt \
    # Firefox is the default scanner browser (--with-deps installs the system libraries it needs); Studio draws its scenes in Chromium.
    && python -m playwright install --with-deps firefox chromium \
    && rm -rf /var/lib/apt/lists/* \
    && chmod -R a+rX /ms-playwright

COPY app ./app

# Run as a normal user; /data is the only writable place.
RUN useradd --create-home --uid 10001 adsify && mkdir -p /data && chown adsify /data
USER adsify
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# One worker on purpose: scan and video jobs run inside the process (see README "Scaling").
# Behind a reverse proxy, set TRUST_PROXY_HEADERS=true so rate limits use the real client address.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
