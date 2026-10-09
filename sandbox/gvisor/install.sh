#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Durabl — gVisor (runsc) o'rnatish skripti
#
# Nima qiladi:
#   1. Tizimni tekshiradi (Linux + root + kerakli buyruqlar)
#   2. Arxitekturani aniqlaydi (x86_64 / aarch64)
#   3. Google'ning rasmiy omboridan `runsc` va `containerd-shim-runsc-v1`
#      yuklab oladi va sha512 summasini tekshiradi
#   4. `/usr/local/bin` ga o'rnatadi
#   5. `runsc install` bilan Docker'ga `runsc` runtime'ini ro'yxatdan o'tkazadi
#   6. Docker'ni qayta ishga tushiradi va sinov konteyneri bilan tasdiqlaydi
#
# Ishlatish:
#   sudo ./install.sh                 # eng yangi versiya
#   sudo GVISOR_RELEASE=20240401 ./install.sh
#   sudo ./install.sh --no-restart    # Docker'ni qayta ishga tushirmaslik
#   ./install.sh --help
# ---------------------------------------------------------------------------
set -euo pipefail

# --- Rangli chiqish ---------------------------------------------------------
if [[ -t 1 ]]; then
    readonly C_RESET=$'\033[0m'
    readonly C_RED=$'\033[1;31m'
    readonly C_GREEN=$'\033[1;32m'
    readonly C_YELLOW=$'\033[1;33m'
    readonly C_BLUE=$'\033[1;34m'
    readonly C_DIM=$'\033[2m'
else
    readonly C_RESET='' C_RED='' C_GREEN='' C_YELLOW='' C_BLUE='' C_DIM=''
fi

#: Qadam raqami — foydalanuvchi qaysi bosqichda ekanini ko'rib turishi uchun.
STEP=0

step()  { STEP=$((STEP + 1)); printf '%s[%d/7]%s %s\n' "$C_BLUE" "$STEP" "$C_RESET" "$1"; }
info()  { printf '      %s%s%s\n' "$C_DIM" "$1" "$C_RESET"; }
ok()    { printf '      %s✓%s %s\n' "$C_GREEN" "$C_RESET" "$1"; }
warn()  { printf '%sOGOHLANTIRISH:%s %s\n' "$C_YELLOW" "$C_RESET" "$1" >&2; }
fail()  { printf '%sXATO:%s %s\n' "$C_RED" "$C_RESET" "$1" >&2; exit 1; }

usage() {
    cat <<'USAGE'
Durabl — gVisor (runsc) o'rnatish

Ishlatish: sudo ./install.sh [parametrlar]

Parametrlar:
  --no-restart     Docker demonini qayta ishga tushirmaydi (keyin o'zingiz qilasiz)
  --no-verify      Yakuniy sinov konteynerini ishga tushirmaydi
  --platform=NOM   gVisor platformasi: systrap (standart), ptrace, kvm
  -h, --help       Shu yordamni chiqaradi

Muhit o'zgaruvchilari:
  GVISOR_RELEASE   Versiya tegi (standart: latest)
  INSTALL_DIR      O'rnatish katalogi (standart: /usr/local/bin)
USAGE
}

# --- Parametrlar ------------------------------------------------------------
RESTART_DOCKER=1
RUN_VERIFY=1
PLATFORM="systrap"
GVISOR_RELEASE="${GVISOR_RELEASE:-latest}"
INSTALL_DIR="${INSTALL_DIR:-/usr/local/bin}"
#: Shu skript joylashgan katalog — runsc-config.json yonida turadi.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-restart) RESTART_DOCKER=0 ;;
        --no-verify)  RUN_VERIFY=0 ;;
        --platform=*) PLATFORM="${1#*=}" ;;
        -h|--help)    usage; exit 0 ;;
        *)            fail "noma'lum parametr: $1 (--help ni ko'ring)" ;;
    esac
    shift
done

printf "%sDurabl — gVisor sandbox o'rnatish%s\n\n" "$C_BLUE" "$C_RESET"

# --- 1-qadam: tizim tekshiruvi ---------------------------------------------
step "Tizim tekshirilmoqda"

KERNEL="$(uname -s)"
if [[ "$KERNEL" != "Linux" ]]; then
    # gVisor — Linux kerneli ustida ishlaydigan foydalanuvchi fazosi kerneli.
    # macOS/Windows'da u printsipial ravishda ishlamaydi.
    printf '%s\n' "${C_YELLOW}gVisor faqat Linux'da ishlaydi (hozirgi tizim: ${KERNEL}).${C_RESET}" >&2
    cat >&2 <<'MACOS_HINT'

  macOS yoki Windows'da ishlab chiqish uchun:

    1. backend/.env faylida sandbox'ni o'chiring:
           SANDBOX_ENABLED=False
       Shunda kod lokal subprocess'da bajariladi (FAQAT development uchun!).

    2. Yoki Docker Desktop'dagi Linux VM ichida emas, haqiqiy Linux
       serverda (yoki Lima/Multipass VM'da) shu skriptni ishga tushiring.

    3. Image'larni baribir build qilish mumkin:
           ./sandbox/build.sh
       va ularni `--runtime=runc` bilan sinab ko'rish mumkin — izolyatsiya
       kuchsizroq bo'ladi, lekin entrypoint shartnomasi bir xil ishlaydi.

MACOS_HINT
    exit 1
fi
ok "kernel: Linux ($(uname -r))"

if [[ "${EUID}" -ne 0 ]]; then
    fail "root huquqi kerak — 'sudo ./install.sh' deb ishga tushiring"
fi
ok "root huquqi bor"

# Kerakli buyruqlar. `sha512sum` coreutils'da, `curl` tarmoq uchun.
for cmd in curl sha512sum install; do
    command -v "$cmd" >/dev/null 2>&1 || fail "'$cmd' buyrug'i topilmadi — uni o'rnating"
done
ok "kerakli buyruqlar joyida"

if ! command -v docker >/dev/null 2>&1; then
    fail "docker topilmadi — avval Docker Engine o'rnating (https://docs.docker.com/engine/install/)"
fi
DOCKER_VERSION="$(docker --version 2>/dev/null || true)"
# `| head` ishlatilmaydi — pipefail + SIGPIPE skriptni uzib qo'yishi mumkin.
ok "docker: ${DOCKER_VERSION%%$'\n'*}"

# --- 2-qadam: arxitektura ---------------------------------------------------
step "Arxitektura aniqlanmoqda"
MACHINE="$(uname -m)"
case "$MACHINE" in
    x86_64|amd64)   ARCH="x86_64" ;;
    aarch64|arm64)  ARCH="aarch64" ;;
    *)              fail "qo'llab-quvvatlanmaydigan arxitektura: $MACHINE (faqat x86_64 va aarch64)" ;;
esac
ok "arxitektura: $ARCH"

# --- 3-qadam: yuklab olish --------------------------------------------------
step "gVisor yuklab olinmoqda (release: ${GVISOR_RELEASE})"
BASE_URL="https://storage.googleapis.com/gvisor/releases/release/${GVISOR_RELEASE}/${ARCH}"
info "manba: ${BASE_URL}"

WORK_DIR="$(mktemp -d)"
# Skript qanday tugasa ham vaqtinchalik kataloglar tozalanadi.
cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT INT TERM

cd "$WORK_DIR"
for artifact in runsc containerd-shim-runsc-v1; do
    info "yuklanmoqda: ${artifact}"
    curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
         --remote-name-all \
         "${BASE_URL}/${artifact}" "${BASE_URL}/${artifact}.sha512" \
        || fail "${artifact} yuklanmadi — release tegi yoki tarmoqni tekshiring"
done
ok "ikki fayl yuklandi"

# --- 4-qadam: yaxlitlikni tekshirish ---------------------------------------
step "sha512 summalari tekshirilmoqda"
# Rasmiy .sha512 fayllari ichida yo'l boshqa bo'lishi mumkin — faqat fayl
# nomini qoldiramiz, aks holda `sha512sum -c` faylni topa olmaydi.
for artifact in runsc containerd-shim-runsc-v1; do
    sed -i -E "s@ +[^ ]*/@  @" "${artifact}.sha512" 2>/dev/null || true
done
sha512sum -c runsc.sha512 containerd-shim-runsc-v1.sha512 \
    || fail "sha512 mos kelmadi — yuklangan fayllarga ishonmang, qayta urinib ko'ring"
ok "summalar to'g'ri"

# --- 5-qadam: o'rnatish -----------------------------------------------------
step "Fayllar ${INSTALL_DIR} ga o'rnatilmoqda"
chmod a+rx runsc containerd-shim-runsc-v1
install -o root -g root -m 0755 -t "$INSTALL_DIR" runsc containerd-shim-runsc-v1 \
    || fail "o'rnatish muvaffaqiyatsiz tugadi"
RUNSC_VERSION="$("$INSTALL_DIR/runsc" --version 2>/dev/null || true)"
ok "runsc: ${RUNSC_VERSION%%$'\n'*}"

# --- 6-qadam: Docker'ga ro'yxatdan o'tkazish -------------------------------
step "Docker'ga runsc runtime'i qo'shilmoqda"

# Runtime argumentlari. Agar `jq` bo'lsa — runsc-config.json'dagi
# `runtimeArgs` ishlatiladi, aks holda quyidagi standart ro'yxat.
RUNSC_ARGS=("--platform=${PLATFORM}" "--network=none" "--overlay2=root:self" "--watchdog-action=panic")
CONFIG_FILE="${SCRIPT_DIR}/runsc-config.json"
if command -v jq >/dev/null 2>&1 && [[ -f "$CONFIG_FILE" ]]; then
    mapfile -t FROM_CONFIG < <(jq -r '.runtimeArgs[]?' "$CONFIG_FILE" 2>/dev/null || true)
    if [[ ${#FROM_CONFIG[@]} -gt 0 ]]; then
        RUNSC_ARGS=("${FROM_CONFIG[@]}")
        info "argumentlar runsc-config.json dan olindi"
    fi
else
    info "jq topilmadi — standart argumentlar ishlatiladi"
fi
info "runtimeArgs: ${RUNSC_ARGS[*]}"

# `runsc install` /etc/docker/daemon.json ga runtime yozuvini qo'shadi.
# Mavjud daemon.json nusxasi saqlanadi — tiklash uchun.
if [[ -f /etc/docker/daemon.json ]]; then
    BACKUP="/etc/docker/daemon.json.durabl-$(date +%Y%m%d%H%M%S).bak"
    cp /etc/docker/daemon.json "$BACKUP"
    info "daemon.json zaxirasi: ${BACKUP}"
fi
"$INSTALL_DIR/runsc" install --runtime=runsc -- "${RUNSC_ARGS[@]}" \
    || fail "'runsc install' bajarilmadi"
ok "runtime ro'yxatga olindi (/etc/docker/daemon.json)"

if [[ "$RESTART_DOCKER" -eq 1 ]]; then
    info "Docker qayta ishga tushirilmoqda"
    if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files docker.service >/dev/null 2>&1; then
        systemctl restart docker || fail "systemctl restart docker muvaffaqiyatsiz"
    elif command -v service >/dev/null 2>&1; then
        service docker restart || fail "service docker restart muvaffaqiyatsiz"
    else
        warn "Docker'ni qayta ishga tushirish usuli topilmadi — qo'lda bajaring"
    fi
    # Demon ko'tarilishini kutamiz (maksimum ~15 soniya).
    for _ in $(seq 1 15); do
        if docker info >/dev/null 2>&1; then break; fi
        sleep 1
    done
    ok "Docker ishlayapti"
else
    warn "--no-restart berildi: runtime faqat Docker qayta ishga tushgandan keyin ishlaydi"
fi

# --- 7-qadam: tasdiqlash ----------------------------------------------------
step "Tekshirilmoqda"
if [[ "$RUN_VERIFY" -eq 0 ]]; then
    info "--no-verify berildi, sinov o'tkazilmadi"
elif ! docker info >/dev/null 2>&1; then
    warn "Docker demoniga ulanilmadi — sinovni qo'lda bajaring"
else
    if docker run --runtime=runsc --rm alpine uname -a; then
        ok "gVisor ishlayapti — yuqoridagi kernel nomi 'gVisor' bo'lishi kerak"
    else
        fail "sinov konteyneri ishga tushmadi ('docker run --runtime=runsc' xatosi)"
    fi
fi

printf '\n%sTayyor.%s Keyingi qadamlar:\n' "$C_GREEN" "$C_RESET"
cat <<'NEXT'
  1. Runner image'larini build qiling:
         ./sandbox/build.sh
  2. backend/.env faylida sandbox'ni yoqing:
         SANDBOX_ENABLED=True
         SANDBOX_RUNTIME=runsc
  3. Worker'ni ishga tushiring:
         python -m app.workers.worker_pool
NEXT
