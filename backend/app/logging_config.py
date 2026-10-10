"""Durabl — strukturalangan logging (structlog) sozlamasi.

Nega structlog: Durabl'ning tamal tamoyillaridan biri — **observability**.
Bitta job'ning yo'li (qabul -> navbat -> worker -> sandbox -> natija) bir
nechta protsessdan o'tadi, shuning uchun loglar matn emas, **maydonli**
(key-value) bo'lishi kerak: `correlation_id` bo'yicha butun zanjirni bitta
so'rov bilan topish mumkin bo'ladi.

Ikki rejim:

* `LOG_FORMAT="json"` — production. Har satr bitta JSON obyekt
  (Loki/Elasticsearch/Datadog to'g'ridan-to'g'ri o'qiydi).
* `LOG_FORMAT="console"` — development. Rangli, odam o'qiydigan ko'rinish.

Standart `logging` (uvicorn, SQLAlchemy, httpx, docker) ham ayni shu quvur
orqali o'tadi — `ProcessorFormatter` tufayli begona loglar ham bir xil
shaklda chiqadi.

Kontekst `contextvars` orqali uzatiladi: middleware `bind_request_context()`
chaqiradi, shundan keyin **shu so'rov ichidagi barcha** log yozuvlariga
`request_id`, `correlation_id`, `user_id` avtomatik qo'shiladi — har bir
`logger.info(...)` chaqiruviga qo'lda uzatish kerak emas.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, cast

import structlog
from structlog.typing import Processor

from app.config import settings
from app.utils.serializers import json_default

#: `setup_logging()` bir martadan ko'p ishlamasligi uchun bayroq.
_configured: bool = False

#: Juda "gapdon" tashqi kutubxonalar — faqat ogohlantirishdan yuqorisi.
_NOISY_LOGGERS: tuple[str, ...] = (
    "asyncio",
    "docker",
    "httpcore",
    "httpx",
    "urllib3",
    "websockets",
)


def _log_json_default(value: Any) -> Any:
    """JSON renderer uchun zaxira: tanilmagan turni `repr` bilan beradi.

    Logging HECH QACHON ilovani yiqitmasligi kerak, shuning uchun
    `json_default` `TypeError` bergan holatda ham satr yozilishi shart.
    """
    try:
        return json_default(value)
    except TypeError:
        return repr(value)


def _shared_processors() -> list[Processor]:
    """structlog va standart `logging` uchun umumiy processor zanjiri."""
    return [
        structlog.contextvars.merge_contextvars,  # request_id/correlation_id/user_id
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]


def _build_renderer() -> Processor:
    """`LOG_FORMAT` bo'yicha yakuniy renderer tanlaydi."""
    if settings.LOG_FORMAT == "json":
        return structlog.processors.JSONRenderer(
            serializer=json.dumps,
            default=_log_json_default,
            ensure_ascii=False,
        )
    return structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())


def _configure_library_loggers() -> None:
    """Tashqi kutubxonalar logger'larini bizning quvurga yo'naltiradi."""
    level = logging.getLevelName(settings.LOG_LEVEL)

    # uvicorn o'zining handler'larini qo'yadi — ularni olib tashlab,
    # root handler'imizga (ProcessorFormatter) propagate qilamiz.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(level)

    # HTTP access logi bizning `RequestLoggingMiddleware` bilan takrorlanadi:
    # development'da qoldiramiz, production'da o'chiramiz.
    logging.getLogger("uvicorn.access").setLevel(
        logging.INFO if settings.DEBUG else logging.WARNING
    )

    # SQL so'rovlari faqat `DB_ECHO=True` bo'lganda ko'rinadi.
    sqlalchemy_level = logging.INFO if settings.DB_ECHO else logging.WARNING
    for name in ("sqlalchemy", "sqlalchemy.engine", "sqlalchemy.pool", "sqlalchemy.orm"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(sqlalchemy_level)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def setup_logging(*, force: bool = False) -> None:
    """Butun ilova uchun logging'ni sozlaydi.

    `main.py` lifespan boshida va har bir worker `main()` funksiyasida
    BIRINCHI chaqiriladigan funksiya. Takroriy chaqiruvlar e'tiborsiz
    qoldiriladi (`force=True` bilan majburan qayta sozlanadi — testlarda
    `LOG_FORMAT` o'zgartirilganda kerak bo'ladi).
    """
    global _configured
    if _configured and not force:
        return

    shared = _shared_processors()

    # structlog logger'lari: zanjir oxirida `wrap_for_formatter` — yakuniy
    # renderlashni standart `logging` handler'iga topshiradi. Shu tufayli
    # structlog va `logging` loglari BITTA joydan chiqadi.
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,  # structlog'dan kelmagan (begona) loglar uchun
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _build_renderer(),
        ],
    )

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(logging.getLevelName(settings.LOG_LEVEL))

    _configure_library_loggers()
    _configured = True


def is_logging_configured() -> bool:
    """`setup_logging()` chaqirilganmi (diagnostika va testlar uchun)."""
    return _configured


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Modul uchun logger qaytaradi.

    Odatiy ishlatilishi — modul boshida:

        from app.logging_config import get_logger
        logger = get_logger(__name__)

    Qaytgan obyekt dangasa (lazy) proxy: `setup_logging()` keyinroq
    chaqirilsa ham, birinchi yozuvda yangi sozlama qo'llanadi.
    """
    logger = structlog.stdlib.get_logger(name) if name else structlog.stdlib.get_logger()
    return cast("structlog.stdlib.BoundLogger", logger)


def bind_request_context(
    *,
    request_id: str | None = None,
    correlation_id: str | None = None,
    user_id: object | None = None,
    job_id: object | None = None,
    **extra: Any,
) -> None:
    """So'rov/job kontekstini joriy `contextvar`ga bog'laydi.

    Shundan keyin ayni shu so'rov (yoki worker vazifasi) ichidagi BARCHA log
    yozuvlariga berilgan maydonlar avtomatik qo'shiladi. `None` qiymatlar
    bog'lanmaydi — log yozuvi bo'sh maydonlar bilan to'lib ketmaydi.

    Args:
        request_id: `X-Request-ID` header'idan yoki yangi yaratilgan.
        correlation_id: Job'ning butun hayot siklini bog'laydigan ID.
        user_id: Autentifikatsiyadan o'tgan foydalanuvchi.
        job_id: Worker kontekstida — bajarilayotgan job.
        **extra: Qo'shimcha maydonlar (`worker_id`, `attempt` kabi).
    """
    values: dict[str, Any] = {
        "request_id": request_id,
        "correlation_id": correlation_id,
        "user_id": None if user_id is None else str(user_id),
        "job_id": None if job_id is None else str(job_id),
        **extra,
    }
    bindable = {key: value for key, value in values.items() if value is not None}
    if bindable:
        structlog.contextvars.bind_contextvars(**bindable)


def clear_request_context() -> None:
    """Kontekstni to'liq tozalaydi — so'rov/vazifa tugaganda chaqiriladi.

    Tozalanmasa, protsessdagi keyingi so'rov eski `request_id` bilan log
    yozishi mumkin (asyncio task'lari contextvar'ni meros qilib oladi).
    """
    structlog.contextvars.clear_contextvars()


__all__ = [
    "bind_request_context",
    "clear_request_context",
    "get_logger",
    "is_logging_configured",
    "setup_logging",
]
