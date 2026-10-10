#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Durabl — sandbox runner image'larini build qilish
#
# Ikki image build qiladi:
#   durabl/runner-python:latest  (settings.SANDBOX_IMAGE_PYTHON)
#   durabl/runner-node:latest    (settings.SANDBOX_IMAGE_NODE)
#
# Build'dan keyin har bir image "smoke test"dan o'tadi: konteyner ichida
# kichik kod bajariladi va result.json shakli tekshiriladi. Shu sinov
# entrypoint shartnomasi buzilmaganini kafolatlaydi.
#
# Ishlatish:
#   ./build.sh                       # ikkisini build qiladi + sinaydi
#   ./build.sh --python-only
#   ./build.sh --no-cache --no-smoke
#   ./build.sh --platform=linux/arm64
#   ./build.sh --runtime=runsc       # smoke testni gVisor bilan o'tkazadi
#   ./build.sh --help
#
# Bu skript macOS'da ham ishlaydi (Docker Desktop bilan) — faqat gVisor
# bo'lmaydi, shuning uchun smoke test standart `runc` runtime'ida o'tadi.
# ---------------------------------------------------------------------------
set -euo pipefail

# --- Rangli chiqish ---------------------------------------------------------
if [[ -t 1 ]]; then
    C_RESET=$'\033[0m'; C_RED=$'\033[1;31m'; C_GREEN=$'\033[1;32m'
    C_YELLOW=$'\033[1;33m'; C_BLUE=$'\033[1;34m'; C_DIM=$'\033[2m'
else
    C_RESET=''; C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''; C_DIM=''
fi
readonly C_RESET C_RED C_GREEN C_YELLOW C_BLUE C_DIM

head()  { printf '\n%s==>%s %s\n' "$C_BLUE" "$C_RESET" "$1"; }
info()  { printf '    %s%s%s\n' "$C_DIM" "$1" "$C_RESET"; }
ok()    { printf '    %s✓%s %s\n' "$C_GREEN" "$C_RESET" "$1"; }
warn()  { printf '%sOGOHLANTIRISH:%s %s\n' "$C_YELLOW" "$C_RESET" "$1" >&2; }
fail()  { printf '%sXATO:%s %s\n' "$C_RED" "$C_RESET" "$1" >&2; exit 1; }

usage() {
    cat <<'USAGE'
Durabl — sandbox image'larini build qilish

Ishlatish: ./build.sh [parametrlar]

Parametrlar:
  --python-only      Faqat Python runner
  --node-only        Faqat Node runner
  --no-cache         Docker keshini ishlatmaslik
  --no-smoke         Build'dan keyin sinov o'tkazmaslik
  --platform=P       Maqsad platforma (masalan linux/amd64, linux/arm64)
  --runtime=R        Smoke test runtime'i (runc yoki runsc)
  --tag=T            Teg (standart: latest)
  -h, --help         Shu yordam

Muhit o'zgaruvchilari:
  SANDBOX_IMAGE_PYTHON   Python image nomi (standart durabl/runner-python:latest)
  SANDBOX_IMAGE_NODE     Node image nomi   (standart durabl/runner-node:latest)
USAGE
}

# --- Parametrlar ------------------------------------------------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BUILD_PYTHON=1
BUILD_NODE=1
NO_CACHE=0
RUN_SMOKE=1
PLATFORM=""
SMOKE_RUNTIME="runc"
TAG="latest"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --python-only) BUILD_NODE=0 ;;
        --node-only)   BUILD_PYTHON=0 ;;
        --no-cache)    NO_CACHE=1 ;;
        --no-smoke)    RUN_SMOKE=0 ;;
        --platform=*)  PLATFORM="${1#*=}" ;;
        --runtime=*)   SMOKE_RUNTIME="${1#*=}" ;;
        --tag=*)       TAG="${1#*=}" ;;
        -h|--help)     usage; exit 0 ;;
        *)             fail "noma'lum parametr: $1 (--help ni ko'ring)" ;;
    esac
    shift
done

PYTHON_IMAGE="${SANDBOX_IMAGE_PYTHON:-durabl/runner-python:${TAG}}"
NODE_IMAGE="${SANDBOX_IMAGE_NODE:-durabl/runner-node:${TAG}}"

command -v docker >/dev/null 2>&1 || fail "docker topilmadi — Docker Engine yoki Docker Desktop o'rnating"
docker info >/dev/null 2>&1 || fail "docker demoniga ulanilmadi — u ishlab turganini tekshiring"

printf '%sDurabl — sandbox image build%s\n' "$C_BLUE" "$C_RESET"
info "python image : ${PYTHON_IMAGE}"
info "node image   : ${NODE_IMAGE}"
info "platforma    : ${PLATFORM:-(host)}"
info "smoke runtime: ${SMOKE_RUNTIME}"

# --- Build yordamchisi ------------------------------------------------------
# $1 — image nomi, $2 — kontekst katalogi, $3 — ko'rinadigan nom
build_image() {
    local image="$1" context="$2" label="$3"
    head "${label} build qilinmoqda"
    [[ -f "${context}/Dockerfile" ]] || fail "Dockerfile topilmadi: ${context}/Dockerfile"

    local args
    args=(build --tag "$image" --file "${context}/Dockerfile")
    [[ "$NO_CACHE" -eq 1 ]] && args+=(--no-cache)
    [[ -n "$PLATFORM" ]] && args+=(--platform "$PLATFORM")
    args+=(--label "io.durabl.built-at=$(date -u +%Y-%m-%dT%H:%M:%SZ)")
    args+=("$context")

    info "docker ${args[*]}"
    docker "${args[@]}" || fail "${label} build qilinmadi"

    # Hajmni `docker image ls` ko'rsatganidek chiqaramiz — `inspect`ning
    # bayt qiymati containerd snapshotter'da boshqacha hisoblanadi.
    local size
    size="$(docker image ls --filter "reference=${image}" --format '{{.Size}}' 2>/dev/null || true)"
    # `| head` ATAYLAB ishlatilmaydi: `set -o pipefail` bilan head quvurni
    # yopganda docker SIGPIPE oladi va skript 141 kodi bilan uzilib qoladi.
    # Birinchi qatorni parametr almashtirish bilan olamiz.
    size="${size%%$'\n'*}"
    # Diqqat: ${var:-...} ichida apostrof ishlatilmaydi — bash parser buziladi.
    [[ -n "$size" ]] || size="aniqlanmadi"
    ok "${label} tayyor (hajm: ${size})"
}

# --- Smoke test -------------------------------------------------------------
# Konteynerni haqiqatan ishga tushiradi va result.json shaklini tekshiradi.
# $1 — image, $2 — runtime nomi (python|node), $3 — ko'rinadigan nom
smoke_test() {
    local image="$1" kind="$2" label="$3"
    head "${label} sinovdan o'tkazilmoqda"

    local work
    work="$(mktemp -d)"
    # Sinov qanday tugasa ham vaqtinchalik katalog tozalanadi.
    trap 'rm -rf "$work"' RETURN

    # `mktemp -d` katalogni 0700 bilan yaratadi — faqat egasi kirishi mumkin.
    # Konteyner esa `--user 10001:10001` ostida ishlaydi va `result.json` ni
    # SHU katalogga yozishi kerak, ya'ni 0700 yetmaydi.
    #
    # Nega bu macOS'da sezilmaydi: Docker Desktop bind-mount huquqlarini
    # host foydalanuvchisiga moslaydi va uid farqini e'tiborsiz qoldiradi.
    # Linux'da esa (CI va production) uid 10001 katalogga umuman kira
    # olmaydi va sinov "result.json yozilmadi" bilan yiqiladi.
    #
    # Ayni yechim backendda ham bor: `WORKDIR_MODE` —
    # `app/execution/sandbox_manager.py`. Ikkisi bir xil bo'lishi kerak,
    # aks holda smoke test production yo'lini tekshirmagan bo'ladi.
    # Xavfsizlik: katalog bir martalik, ichida sir yo'q va sinov tugashi
    # bilan o'chiriladi.
    chmod 0777 "$work"

    if [[ "$kind" == "python" ]]; then
        cat > "${work}/main.py" <<'SMOKE_PY'
def main(x, factor=2):
    """Sinov funksiyasi: payload bilan chaqiriladi."""
    print("durabl smoke test: python")
    return {"value": x * factor, "runtime": "python"}
SMOKE_PY
    else
        cat > "${work}/main.js" <<'SMOKE_JS'
module.exports.main = function main(x, opts = {}) {
  // Sinov funksiyasi: payload bilan chaqiriladi.
  console.log("durabl smoke test: node");
  return { value: x * (opts.factor || 1), runtime: "node" };
};
SMOKE_JS
    fi
    printf '%s\n' '{"args": [21], "kwargs": {"factor": 2}}' > "${work}/payload.json"

    local run_args
    run_args=(run --rm --network=none --read-only
              --tmpfs /tmp:rw,noexec,nosuid,size=32m
              --memory=256m --cpus=0.5 --pids-limit=50
              --cap-drop=ALL --security-opt no-new-privileges
              --user 10001:10001
              -v "${work}:/sandbox:rw")
    if [[ "$SMOKE_RUNTIME" != "runc" ]]; then
        run_args+=(--runtime="$SMOKE_RUNTIME")
    fi
    # Seccomp profili bo'lsa — u ham sinovga qo'shiladi.
    if [[ -f "${SCRIPT_DIR}/gvisor/seccomp-profile.json" ]]; then
        run_args+=(--security-opt "seccomp=${SCRIPT_DIR}/gvisor/seccomp-profile.json")
    fi
    run_args+=("$image")

    if ! docker "${run_args[@]}"; then
        fail "${label}: konteyner xato bilan tugadi"
    fi
    [[ -f "${work}/result.json" ]] || fail "${label}: result.json yozilmadi"

    info "result.json: $(cat "${work}/result.json")"
    # Shartnoma tekshiruvi: ok=true, exit_code=0, result.value=42
    if command -v python3 >/dev/null 2>&1; then
        python3 - "${work}/result.json" <<'VERIFY_PY' || fail "${label}: result.json shartnomaga mos emas"
import json
import sys

required = (
    "ok", "exit_code", "result", "error", "error_type",
    "traceback", "duration_ms", "stdout_bytes", "stderr_bytes",
)
with open(sys.argv[1], encoding="utf-8") as handle:
    doc = json.load(handle)

missing = [key for key in required if key not in doc]
if missing:
    print(f"result.json da kalitlar yo'q: {missing}", file=sys.stderr)
    raise SystemExit(1)
if not doc["ok"] or doc["exit_code"] != 0:
    print(f"konteyner xato qaytardi: {doc}", file=sys.stderr)
    raise SystemExit(1)
if not isinstance(doc["result"], dict) or doc["result"].get("value") != 42:
    print(f"natija kutilganidan farq qiladi: {doc['result']}", file=sys.stderr)
    raise SystemExit(1)
VERIFY_PY
    else
        warn "python3 topilmadi — result.json faqat ko'z bilan tekshirildi"
    fi
    ok "${label}: entrypoint shartnomasi bajarildi (result.value=42)"
}

# --- Asosiy oqim ------------------------------------------------------------
if [[ "$BUILD_PYTHON" -eq 1 ]]; then
    build_image "$PYTHON_IMAGE" "${SCRIPT_DIR}/runners/python" "Python runner"
fi
if [[ "$BUILD_NODE" -eq 1 ]]; then
    build_image "$NODE_IMAGE" "${SCRIPT_DIR}/runners/node" "Node runner"
fi

if [[ "$RUN_SMOKE" -eq 1 ]]; then
    [[ "$BUILD_PYTHON" -eq 1 ]] && smoke_test "$PYTHON_IMAGE" python "Python runner"
    [[ "$BUILD_NODE" -eq 1 ]] && smoke_test "$NODE_IMAGE" node "Node runner"
else
    warn "--no-smoke berildi: image'lar sinovdan o'tmadi"
fi

head "Tayyor"
[[ "$BUILD_PYTHON" -eq 1 ]] && info "$PYTHON_IMAGE"
[[ "$BUILD_NODE" -eq 1 ]] && info "$NODE_IMAGE"
cat <<'NEXT'

    Keyingi qadam — backend/.env da image nomlarini ko'rsatish:
        SANDBOX_ENABLED=True
        SANDBOX_RUNTIME=runsc
        SANDBOX_IMAGE_PYTHON=durabl/runner-python:latest
        SANDBOX_IMAGE_NODE=durabl/runner-node:latest
NEXT
