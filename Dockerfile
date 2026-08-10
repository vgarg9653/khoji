# Khoji.AI WhatsApp bot — Cloud Run image.
#
# Only the bot ships here. The crawler and its heavy dependencies (Playwright,
# Chromium, tesseract) stay out: the container serves a dataset that was built
# and verified beforehand, so the image stays small and starts fast, which
# matters because Cloud Run scales to zero and cold starts are on the student's
# clock.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Runtime dependencies only — no crawler, no browser.
COPY requirements-bot.txt .
RUN pip install --no-cache-dir -r requirements-bot.txt

COPY bot/ ./bot/
COPY deliverables/dataset/bot_matching.json ./data/bot_matching.json

ENV KHOJI_DATA=/app/data/bot_matching.json \
    PORT=8080

# Run as a non-root user; Cloud Run does not require it, but a webhook that
# accepts arbitrary text from the internet should not be root.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser /app
USER appuser

EXPOSE 8080

# Cloud Run injects $PORT and terminates TLS for us. One worker with several
# threads suits this workload: replies are I/O-bound on Gemini and Firestore.
CMD exec uvicorn bot.app:app --host 0.0.0.0 --port ${PORT} --workers 1
