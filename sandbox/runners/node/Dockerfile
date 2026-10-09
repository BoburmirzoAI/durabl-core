# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Durabl — Node runner image (minimal, bir martalik konteyner)
#
# Bu image mijoz JavaScript kodini gVisor (runsc) sandbox ichida bajaradi.
# Konteyner bitta job uchun yaratiladi va tugashi bilan o'chiriladi —
# shuning uchun HEALTHCHECK kerak emas.
#
# Build:
#   docker build -t durabl/runner-node:latest sandbox/runners/node
#
# Ishga tushirish (backend `sandbox_manager` shunga yaqin buyruq yasaydi):
#   docker run --rm --runtime=runsc --network=none \
#     --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m \
#     --memory=256m --cpus=0.5 --pids-limit=50 \
#     --user 10001:10001 --cap-drop=ALL --security-opt no-new-privileges \
#     -v "$PWD/job:/sandbox:rw" durabl/runner-node:latest
# ---------------------------------------------------------------------------
FROM node:22-alpine

LABEL org.opencontainers.image.title="durabl-runner-node" \
      org.opencontainers.image.description="Durabl Node sandbox runner" \
      org.opencontainers.image.vendor="Durabl" \
      io.durabl.runtime="node"

# HOME/TMPDIR=/tmp — `--read-only` rootfs'da yoziladigan yagona joy tmpfs.
# NODE_OPTIONS — ichki xotira chegarasi konteyner limitidan past turadi.
ENV NODE_ENV=production \
    HOME=/tmp \
    TMPDIR=/tmp \
    npm_config_update_notifier=false \
    NO_UPDATE_NOTIFIER=1 \
    NODE_OPTIONS=--max-old-space-size=192 \
    DURABL_SANDBOX_WORKDIR=/sandbox

# Imtiyozsiz foydalanuvchi va kataloglar.
# `node:alpine` image'ida `node` (uid 1000) foydalanuvchisi bor — bizga
# 10001 kerak (`settings.SANDBOX_USER`). npm/npx olib tashlanadi: sandbox
# ichida paket o'rnatilmaydi.
RUN set -eux; \
    addgroup -g 10001 -S sandbox; \
    adduser -u 10001 -G sandbox -S -H -s /sbin/nologin sandbox; \
    mkdir -p /sandbox /opt/durabl; \
    rm -rf /usr/local/lib/node_modules/npm \
           /usr/local/lib/node_modules/corepack \
           /usr/local/bin/npm /usr/local/bin/npx \
           /usr/local/bin/corepack \
           /opt/yarn* /usr/local/bin/yarn /usr/local/bin/yarnpkg \
           /root/.npm /root/.cache /tmp/* ; \
    chown 10001:10001 /sandbox; \
    chmod 0755 /sandbox

# Entrypoint — mijoz yoza olmaydigan joyda (/opt), faqat o'qish uchun.
COPY --chown=root:root entrypoint.js /opt/durabl/entrypoint.js
RUN chmod 0444 /opt/durabl/entrypoint.js

# Mijoz kodi va natija fayli shu katalogda bo'ladi (backend volume sifatida ulaydi).
# `VOLUME` ataylab e'lon qilinmaydi: backend `/sandbox` ni bind-mount qiladi,
# e'lon esa har konteyner uchun anonim volume yaratib, "orphan"larni ko'paytiradi.
WORKDIR /sandbox

# Root huquqlari bilan hech qachon ishlamaydi.
USER 10001:10001

ENTRYPOINT ["node", "/opt/durabl/entrypoint.js"]
