#!/usr/bin/env bash
# =============================================================================
# Durabl — namuna ma'lumot yaratish skripti (`make seed`)
#
# Nima qiladi:
#   1. Demo foydalanuvchini ro'yxatdan o'tkazadi (mavjud bo'lsa — faqat kiradi)
#   2. API kalit yaratadi
#   3. Bir nechta namuna job yuboradi: muvaffaqiyatli, xato beradigan,
#      kechiktirilgan va Node runtime'li
#
# Talab: API ishlab turishi kerak (`make dev`), `curl` va `python3`.
# Sozlash: API_URL, SEED_EMAIL, SEED_PASSWORD muhit o'zgaruvchilari.
# =============================================================================
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
SEED_EMAIL="${SEED_EMAIL:-demo@durabl.dev}"
SEED_PASSWORD="${SEED_PASSWORD:-DurablDemo123!}"
API_V1="${API_URL}/api/v1"

# --- Yordamchilar ---------------------------------------------------------

#: JSON ichidan bitta kalitni oladi (jq o'rniga python3 — qo'shimcha o'rnatish shart emas)
json_get() {
    python3 -c '
import json, sys
key = sys.argv[1]
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)
value = data
for part in key.split("."):
    if not isinstance(value, dict) or part not in value:
        sys.exit(1)
    value = value[part]
print(value)
' "$1" 2>/dev/null || true
}

say() { printf '  %s\n' "$*"; }

# --- 0. API tirikligini tekshirish ---------------------------------------

say "API tekshirilmoqda: ${API_URL}/health"
if ! curl -fsS --max-time 5 "${API_URL}/health" >/dev/null 2>&1; then
    echo "XATO: API javob bermadi (${API_URL}/health). Avval 'make dev' bajaring." >&2
    exit 1
fi

# --- 1. Ro'yxatdan o'tish yoki kirish ------------------------------------

say "Demo foydalanuvchi: ${SEED_EMAIL}"
register_body=$(printf '{"email":"%s","password":"%s"}' "$SEED_EMAIL" "$SEED_PASSWORD")

curl -fsS -X POST "${API_V1}/auth/register" \
    -H 'Content-Type: application/json' \
    -d "$register_body" >/dev/null 2>&1 \
    && say "ro'yxatdan o'tdi" \
    || say "allaqachon mavjud (yoki ro'yxatdan o'tish o'tkazib yuborildi) — kiramiz"

login_response=$(curl -fsS -X POST "${API_V1}/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$register_body") || {
    echo "XATO: kirish muvaffaqiyatsiz. Parol siyosati mos kelmasligi mumkin." >&2
    exit 1
}

TOKEN=$(printf '%s' "$login_response" | json_get access_token)
if [ -z "${TOKEN}" ]; then
    echo "XATO: access_token olinmadi. Javob: ${login_response}" >&2
    exit 1
fi
say "token olindi"

AUTH=(-H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json')

# --- 2. API kalit yaratish -----------------------------------------------

api_key_response=$(curl -fsS -X POST "${API_V1}/api-keys" "${AUTH[@]}" \
    -d '{"name":"seed-kaliti"}' 2>/dev/null) || api_key_response=""
RAW_KEY=$(printf '%s' "$api_key_response" | json_get key)
if [ -n "${RAW_KEY}" ]; then
    say "API kalit yaratildi: ${RAW_KEY}"
    say "(bu kalit boshqa ko'rsatilmaydi — SDK testlari uchun saqlab qo'ying)"
else
    say "API kalit yaratilmadi (o'tkazib yuborildi)"
fi

# --- 3. Namuna job'lar ---------------------------------------------------

#: Job yuborish: $1 — tavsif, $2 — JSON tanasi
submit_job() {
    local label="$1" body="$2" response job_id
    response=$(curl -fsS -X POST "${API_V1}/jobs" "${AUTH[@]}" \
        -H "Idempotency-Key: seed-$(date +%s)-${RANDOM}" \
        -d "$body" 2>/dev/null) || {
        say "${label}: YUBORILMADI"
        return 0
    }
    job_id=$(printf '%s' "$response" | json_get id)
    say "${label}: ${job_id:-?}"
}

say "namuna job'lar yuborilmoqda..."

# DIQQAT — `payload` bu `args`/`kwargs` konverti, oddiy ma'lumot lug'ati EMAS
# (docs/API.md §6.3 "Kod shartnomasi"). Entrypoint `main(*args, **kwargs)` deb
# chaqiradi, shuning uchun:
#   {"args": [[1,2,3]]}  -> main([1,2,3])
#   {"numbers": [1,2,3]} -> main()  — argument UZATILMAYDI (eng ko'p uchraydigan xato)
# Bundan tashqari `payload` butunlay yuborilmasa funksiya UMUMAN chaqirilmaydi va
# job muvaffaqiyatli tugaydi — shu sababli ataylab yiqiladigan namunalarga ham
# bo'sh `{"args": []}` konverti berilgan.

submit_job "muvaffaqiyatli (python)" '{
  "code": "def main(sonlar):\n    return {\"jami\": sum(sonlar)}\n",
  "runtime": "python",
  "payload": {"args": [[1, 2, 3, 4, 5]]},
  "timeout_seconds": 10,
  "max_retries": 1,
  "priority": "normal",
  "tags": ["seed", "misol"]
}'

submit_job "xato beradigan (retry + DLQ)" '{
  "code": "def main():\n    raise RuntimeError(\"ataylab xato — DLQ namunasi\")\n",
  "runtime": "python",
  "payload": {"args": []},
  "timeout_seconds": 5,
  "max_retries": 2,
  "priority": "low",
  "tags": ["seed", "xato"]
}'

submit_job "sekin (timeout namunasi)" '{
  "code": "import time\n\ndef main():\n    time.sleep(30)\n    return \"hech qachon qaytmaydi\"\n",
  "runtime": "python",
  "payload": {"args": []},
  "timeout_seconds": 3,
  "max_retries": 0,
  "priority": "low",
  "tags": ["seed", "timeout"]
}'

submit_job "node runtime" '{
  "code": "module.exports.main = async function (payload) {\n  return { salom: payload && payload.ism ? payload.ism : \"dunyo\" };\n};\n",
  "runtime": "node",
  "payload": {"args": [{"ism": "Durabl"}]},
  "timeout_seconds": 10,
  "max_retries": 1,
  "priority": "high",
  "tags": ["seed", "node"]
}'

echo ""
say "Tayyor. Dashboard: http://localhost:3000/jobs"
say "Job'lar ro'yxati: curl -H \"Authorization: Bearer \$TOKEN\" ${API_V1}/jobs"
