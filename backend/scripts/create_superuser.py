"""Durabl — admin (superuser) yaratish skripti.

## Nega alohida skript

Birinchi admin'ni API orqali yaratib bo'lmaydi: `POST /auth/register` har doim
oddiy foydalanuvchi yaratadi, `PUT /admin/users/{id}` esa allaqachon admin
bo'lishni talab qiladi. Ya'ni "tovuq va tuxum" muammosi — uni faqat DB'ga
bevosita yozish bilan yechish mumkin.

## Ikki rejim

**Interaktiv** (terminal bor):

```bash
make createsuperuser
```

**Interaktivsiz** (CI, skript, Docker):

```bash
EMAIL=admin@durabl.dev PASSWORD='Parol12345' make createsuperuser
# yoki
python -m scripts.create_superuser --email admin@durabl.dev --password 'Parol12345'
```

## Mavjud foydalanuvchi

Agar shu email allaqachon bo'lsa, skript YANGISINI yaratmaydi — uni admin
darajasiga ko'tarishni taklif qiladi (`--promote` bilan so'ramasdan).

## Validatsiya

Parol va email ILOVANING O'Z qoidalaridan o'tadi (`RegisterRequest` sxemasi),
shuning uchun bu yerda yaratilgan hisob API orqali ham kira oladi. Parol
`app.utils.security.hash_password` bilan xeshlanadi — API bilan AYNI mexanizm.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select

# Skript `backend/` ildizidan ham, `python -m scripts.create_superuser` orqali
# ham ishlashi uchun loyiha yo'lini qo'shamiz.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import close_db, session_scope
from app.logging_config import get_logger, setup_logging
from app.models import User
from app.schemas.auth import RegisterRequest
from app.utils.security import hash_password

logger = get_logger(__name__)

#: Chiqish kodlari — CI shular bo'yicha qaror qiladi.
EXIT_OK = 0
EXIT_INVALID = 1
EXIT_ABORTED = 2
EXIT_DB = 3


def _emit(line: str = "") -> None:
    """Hisobotni `stdout` ga yozadi (log emas — odam o'qishi uchun)."""
    print(line, flush=True)


def _prompt_email(default: str | None) -> str:
    """Email so'raydi. Terminal bo'lmasa — xato (interaktivsiz rejim kerak)."""
    if default:
        return default
    if not sys.stdin.isatty():
        raise SystemExit(
            "XATO: terminal yo'q. Interaktivsiz rejim uchun EMAIL va PASSWORD bering:\n"
            "  EMAIL=admin@durabl.dev PASSWORD='Parol12345' make createsuperuser"
        )
    return input("Email: ").strip()


def _prompt_password(default: str | None) -> str:
    """Parolni ikki marta so'raydi va mos kelishini tekshiradi."""
    if default:
        return default
    if not sys.stdin.isatty():
        raise SystemExit("XATO: terminal yo'q — PASSWORD o'zgaruvchisini bering.")
    while True:
        first = getpass.getpass("Parol: ")
        second = getpass.getpass("Parolni takrorlang: ")
        if first == second:
            return first
        _emit("Parollar mos kelmadi — qaytadan urinib ko'ring.")


def _validate(email: str, password: str, full_name: str | None) -> RegisterRequest:
    """Ilovaning O'Z sxemasi bilan tekshiradi (API bilan bir xil qoidalar)."""
    try:
        return RegisterRequest(email=email, password=password, full_name=full_name)
    except ValidationError as exc:
        _emit("\nKiritilgan ma'lumot qoidalarga mos emas:\n")
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"]) or "qiymat"
            _emit(f"  * {field}: {error['msg']}")
        _emit()
        raise SystemExit(EXIT_INVALID) from exc


async def _create_or_promote(
    *,
    email: str,
    password: str,
    full_name: str | None,
    promote: bool,
    assume_yes: bool,
) -> int:
    """Admin yaratadi yoki mavjudini ko'taradi. Chiqish kodini qaytaradi."""
    async with session_scope() as session:
        existing: User | None = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()

        if existing is not None:
            if existing.is_admin and existing.is_active:
                _emit(f"\n  '{email}' allaqachon FAOL ADMIN. O'zgarish kiritilmadi.\n")
                return EXIT_OK

            if not (promote or assume_yes):
                if not sys.stdin.isatty():
                    _emit(
                        f"\nXATO: '{email}' mavjud, lekin admin emas.\n"
                        "Uni ko'tarish uchun `--promote` bayrog'ini qo'shing.\n"
                    )
                    return EXIT_ABORTED
                # `input()` bloklaydi — uni alohida oqimda chaqiramiz, aks
                # holda event loop to'xtab qoladi (ruff ASYNC250).
                answer = (
                    (
                        await asyncio.to_thread(
                            input,
                            f"\n'{email}' allaqachon mavjud. Admin darajasiga ko'tarilsinmi? [y/N] ",
                        )
                    )
                    .strip()
                    .lower()
                )
                if answer != "y":
                    _emit("Bekor qilindi.\n")
                    return EXIT_ABORTED

            existing.is_admin = True
            existing.is_active = True
            await session.flush()
            _emit(
                f"\n  KO'TARILDI: {email}\n"
                f"    id        {existing.id}\n"
                f"    is_admin  True\n"
                f"    is_active True\n"
            )
            logger.info("superuser ko'tarildi", email=email, user_id=str(existing.id))
            return EXIT_OK

        user = User(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            is_active=True,
            is_admin=True,
        )
        session.add(user)
        await session.flush()

        _emit(
            f"\n  YARATILDI: {email}\n"
            f"    id        {user.id}\n"
            f"    full_name {full_name or '—'}\n"
            f"    is_admin  True\n"
            f"    is_active True\n"
        )
        _emit("  Endi shu hisob bilan kirishingiz mumkin:")
        _emit("    POST /api/v1/auth/login  yoki  http://localhost:3000/login\n")
        logger.info("superuser yaratildi", email=email, user_id=str(user.id))
        return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    """CLI argumentlari."""
    parser = argparse.ArgumentParser(
        prog="create_superuser",
        description="Durabl uchun admin (superuser) hisobini yaratadi.",
        epilog=(
            "Misollar:\n"
            "  python -m scripts.create_superuser\n"
            "  python -m scripts.create_superuser --email a@b.dev --password 'Parol12345'\n"
            "  EMAIL=a@b.dev PASSWORD='Parol12345' python -m scripts.create_superuser\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--email", default=os.getenv("EMAIL"), help="Admin email'i")
    parser.add_argument(
        "--password", default=os.getenv("PASSWORD"), help="Parol (CI uchun; terminalda so'raladi)"
    )
    parser.add_argument(
        "--full-name", default=os.getenv("FULL_NAME"), help="To'liq ism (majburiy emas)"
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help="Mavjud foydalanuvchini so'ramasdan admin qiladi",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Barcha savollarga 'ha' deb javob beradi"
    )
    return parser


async def main() -> int:
    """Kirish nuqtasi."""
    setup_logging()
    args = build_parser().parse_args()

    _emit("\n  Durabl — admin hisobi yaratish\n  " + "-" * 32)

    email = _prompt_email(args.email)
    password = _prompt_password(args.password)
    validated = _validate(email, password, args.full_name)

    try:
        return await _create_or_promote(
            email=str(validated.email),
            password=validated.password,
            full_name=validated.full_name,
            promote=args.promote,
            assume_yes=args.yes,
        )
    except Exception as exc:
        _emit(f"\nXATO: bazaga yozib bo'lmadi — {type(exc).__name__}: {exc}\n")
        _emit("  Baza ko'tarilganmi? Migratsiya bajarilganmi (`make migrate`)?\n")
        logger.error("superuser yaratilmadi", error=str(exc))
        return EXIT_DB
    finally:
        await close_db()


def run() -> None:
    """Sinxron o'ram (`python -m scripts.create_superuser`)."""
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        _emit("\nBekor qilindi.\n")
        raise SystemExit(EXIT_ABORTED) from None


if __name__ == "__main__":
    run()
