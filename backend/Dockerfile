# =============================================================================
# Durabl backend (API) — ko'p qatlamli (multi-stage) image
#
#   builder — virtual muhit yasaydi va kutubxonalarni o'rnatadi
#   runtime — faqat tayyor venv + ilova kodi (minimal, non-root)
#
# Build: docker build -t durabl/api:latest -f backend/Dockerfile backend
# =============================================================================

# -----------------------------------------------------------------------------
# 1-qatlam: builder — kutubxonalarni alohida venv ichiga o'rnatadi
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS builder

#: Kompilyatsiya kerak bo'lsa (wheel topilmasa) — faqat builder qatlamida
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

#: Virtual muhit — runtime qatlamiga bitta katalog sifatida ko'chiriladi
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Avval FAQAT requirements — kod o'zgarganda bu qatlam keshdan olinadi
COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

# -----------------------------------------------------------------------------
# 2-qatlam: runtime — ishlaydigan minimal image
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

#: Python xatti-harakati: bufer yo'q (loglar darhol chiqadi), .pyc yozilmaydi
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    TZ=UTC

#: `curl` — HEALTHCHECK va diagnostika uchun, `tini` — to'g'ri signal uzatish
#  (SIGTERM uvicorn/worker'ga yetib borishi kerak: graceful shutdown)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/*

#: Non-root foydalanuvchi — konteyner ichidagi kod root huquqi bilan ishlamaydi
RUN groupadd --gid 10001 durabl \
    && useradd --uid 10001 --gid 10001 --create-home --shell /bin/bash durabl

# Tayyor virtual muhit
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Ilova kodi (.dockerignore keraksizlarini chiqarib tashlaydi)
COPY --chown=durabl:durabl . /app

USER durabl

EXPOSE 8000

#: `/health` endpointi DB va Redis holatini tekshiradi.
#  Python orqali so'rov — tashqi bog'liqlik kerak emas.
HEALTHCHECK --interval=15s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1

#: tini — PID 1 sifatida zombie protsesslarni yig'adi va signalni uzatadi
ENTRYPOINT ["/usr/bin/tini", "--"]

#: Production'da worker soni `--workers` bilan beriladi (docker-compose.prod.yml)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
