# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Durabl — Python runner image (minimal, bir martalik konteyner)
#
# Bu image mijoz kodini gVisor (runsc) sandbox ichida bajaradi. Konteyner
# bitta job uchun yaratiladi va tugashi bilan o'chiriladi — shuning uchun
# HEALTHCHECK kerak emas.
#
# Build:
#   docker build -t durabl/runner-python:latest sandbox/runners/python
#
# Ishga tushirish (backend `sandbox_manager` shunga yaqin buyruq yasaydi):
#   docker run --rm --runtime=runsc --network=none \
#     --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m \
#     --memory=256m --cpus=0.5 --pids-limit=50 \
#     --user 10001:10001 --cap-drop=ALL --security-opt no-new-privileges \
#     -v "$PWD/job:/sandbox:rw" durabl/runner-python:latest
# ---------------------------------------------------------------------------
FROM python:3.12-slim

# Litsenziya va ownership metama'lumotlari (image inventarizatsiyasi uchun).
LABEL org.opencontainers.image.title="durabl-runner-python" \
      org.opencontainers.image.description="Durabl Python sandbox runner" \
      org.opencontainers.image.vendor="Durabl" \
      io.durabl.runtime="python"

# PYTHONDONTWRITEBYTECODE — `--read-only` rootfs'da .pyc yozishga urinmasligi uchun.
# PYTHONUNBUFFERED    — stdout darhol konteyner logiga tushishi uchun.
# PYTHONFAULTHANDLER  — segfault bo'lsa ham izma-iz chiqsin.
# HOME=/tmp           — kutubxonalar uy katalogiga yozishga urinsa, tmpfs'ga tushadi.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONHASHSEED=random \
    PYTHONNOUSERSITE=1 \
    HOME=/tmp \
    TMPDIR=/tmp \
    PIP_NO_CACHE_DIR=1 \
    DURABL_SANDBOX_WORKDIR=/sandbox

# Imtiyozsiz foydalanuvchi va kataloglar.
# `pip`/`setuptools`/`wheel` olib tashlanadi: sandbox ichida hech narsa
# o'rnatilmaydi, ular esa hujum yuzasini kengaytiradi.
RUN set -eux; \
    groupadd --gid 10001 sandbox; \
    useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin sandbox; \
    mkdir -p /sandbox /opt/durabl; \
    python -m pip uninstall -y pip setuptools wheel 2>/dev/null || true; \
    rm -rf /usr/local/lib/python3.12/ensurepip \
           /usr/local/lib/python3.12/idlelib \
           /usr/local/lib/python3.12/tkinter \
           /usr/local/lib/python3.12/lib2to3 \
           /usr/local/lib/python3.12/turtledemo \
           /usr/local/lib/python3.12/site-packages/pip* \
           /usr/local/lib/python3.12/site-packages/setuptools* \
           /usr/local/lib/python3.12/site-packages/wheel* \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.12 \
           /usr/local/bin/wheel \
           /root/.cache /var/lib/apt/lists/* /var/cache/apt/* /tmp/* ; \
    find /usr/local/lib/python3.12 -name '__pycache__' -type d -prune -exec rm -rf {} + ; \
    find /usr/local/lib/python3.12 -name '*.pyc' -delete ; \
    chown 10001:10001 /sandbox; \
    chmod 0755 /sandbox

# Entrypoint — mijoz yoza olmaydigan joyda (/opt), faqat o'qish uchun.
COPY --chown=root:root entrypoint.py /opt/durabl/entrypoint.py
RUN chmod 0444 /opt/durabl/entrypoint.py

# Mijoz kodi va natija fayli shu katalogda bo'ladi (backend volume sifatida ulaydi).
# `VOLUME` ataylab e'lon qilinmaydi: backend `/sandbox` ni bind-mount qiladi,
# e'lon esa har konteyner uchun anonim volume yaratib, "orphan"larni ko'paytiradi.
WORKDIR /sandbox

# Root huquqlari bilan hech qachon ishlamaydi (`settings.SANDBOX_USER`).
USER 10001:10001

# `-u` — buferlanmagan chiqish (real vaqtli log yig'ish uchun).
ENTRYPOINT ["python", "-u", "/opt/durabl/entrypoint.py"]
