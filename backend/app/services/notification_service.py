"""Durabl — operator bildirishnomalari (alert) servisi.

## Bu servis nima uchun kerak

Durabl o'zini o'zi davolaydigan tizim: lease tugasa job qayta navbatga
tushadi, retry'lar tugasa DLQ'ga boradi, webhook ko'p xato bersa o'chadi.
Lekin bu mexanizmlarning hammasi **jimgina** ishlaydi. Agar DLQ 5000 ta
job bilan to'lib ketsa yoki barcha worker'lar o'lsa — tizim "ishlashda davom
etadi", faqat hech narsa bajarilmaydi. Shu holatni ODAMGA aytadigan qatlam
kerak, va ayni shu qatlam `NotificationService`.

## Eng muhim dizayn qarori: HECH QANDAY BOG'LIQLIK YO'Q

Bu servis **eng oxirgi himoya chizig'i**. U quyidagilarga MURAJAAT QILMAYDI:

* **Redis** — chunki alert'ning eng ko'p kerak bo'ladigan payti aynan Redis
  qulagan payt. Redis'ga tayangan alert o'sha paytda ishlamaydi.
* **PostgreSQL** — ayni mulohaza (DB qulasa ham xabar yetib borishi kerak).
* **`webhook_service`** — u DB va Redis bilan ishlaydi, demak ayni muammo.

Shuning uchun konstruktor BO'SH (`NotificationService()`) va yagona tashqi
kanal — `httpx` bilan to'g'ridan-to'g'ri HTTP (`ALERT_WEBHOOK_URL`) yoki
`smtplib` bilan SMTP. Ikkisi ham hech qanday ichki servisga bog'liq emas.

## Bo'g'ish (throttle) — xotirada, ataylab

Bir xil alert 5 daqiqada bir martadan ko'p yuborilmaydi (`THROTTLE_WINDOW_SECONDS`).
Hisob **modul darajasidagi oddiy lug'at**da (`_THROTTLE`) yuritiladi, Redis'da
EMAS. Oqibati bilib turib qabul qilingan:

* har protsess (API, worker, scheduler) o'z hisobini yuritadi, ya'ni 3 ta
  protsess eng yomon holatda 3 ta bir xil xabar yuboradi;
* buning evaziga bo'g'ish Redis qulaganda ham ISHLAYDI — ya'ni "DLQ to'lib
  ketdi" xabari minutda 600 marta takrorlanib Slack kanalini bo'g'masligi
  kafolatlanadi.

Taqsimlangan (butun klaster bo'yicha yagona) bo'g'ish kerak bo'lsa, u alohida
qatlam sifatida qo'shilishi kerak — lekin Redis'siz zaxira yo'li SHU YERDA
qolishi shart.

## Xato tashlamaslik kafolati

Hech bir metod istisno tashlamaydi. Bildirishnoma yuborilmasligi — noqulaylik;
asosiy ishni (job bajarilishini, webhook yuborilishini) to'xtatish esa
nosozlik. Shu sababli `alert()` muvaffaqiyatni `bool` bilan bildiradi,
`notify_*` metodlari esa umuman hech narsa qaytarmaydi.

Qatlam qoidasi: `fastapi` import QILINMAYDI — ayni shu kod worker
protsesslarida ham ishlaydi.
"""

from __future__ import annotations

import asyncio
import smtplib
import uuid
from datetime import datetime
from email.message import EmailMessage
from typing import Any, Final
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.constants import Priority, StrEnum
from app.logging_config import get_logger
from app.utils.time_utils import isoformat, utcnow

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Daraja (level)
# ---------------------------------------------------------------------------


class AlertLevel(StrEnum):
    """Alert jiddiyligi.

    `app.constants` da bunday enum yo'q va o'sha faylga tegish taqiqlangan,
    shuning uchun enum shu modulda ta'riflangan — lekin loyihaning bazaviy
    `StrEnum` klassidan voris, ya'ni `str` bilan solishtirish va JSON'ga
    serialize bo'lish bir xil ishlaydi. Shu tufayli `alert(level=...)`
    argumenti shartnomadagi `str` turini saqlab qoladi: enum ham, oddiy matn
    ham qabul qilinadi.
    """

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


#: Daraja -> Slack attachment rangi. Slack "good"/"warning"/"danger" nomlarini
#: ham tushunadi, lekin hex kod boshqa qabul qiluvchilar (Mattermost,
#: Discord'ning Slack-mos endpointi, o'z panelimiz) uchun ham bir xil ishlaydi.
LEVEL_COLORS: Final[dict[str, str]] = {
    AlertLevel.INFO.value: "#2e7d32",  # yashil
    AlertLevel.WARNING.value: "#ed6c02",  # to'q sariq
    AlertLevel.ERROR.value: "#d32f2f",  # qizil
    AlertLevel.CRITICAL.value: "#6a1b9a",  # binafsha (qizildan ham jiddiy)
}

#: Noma'lum daraja berilganda ishlatiladigan zaxira.
DEFAULT_LEVEL: Final = AlertLevel.WARNING


# ---------------------------------------------------------------------------
# Bo'g'ish (throttle)
# ---------------------------------------------------------------------------

#: Bir xil kalitli alert shu muddatda bir martadan ko'p yuborilmaydi (soniya).
THROTTLE_WINDOW_SECONDS: Final = 300.0

#: Lug'atdagi maksimal kalit soni. Oshsa eng eski yozuvlar tashlanadi —
#: aks holda "har job uchun alohida kalit" kabi xato ishlatish xotirani
#: cheksiz o'stirardi (bu protsess umri bo'yi yashaydigan global lug'at).
MAX_THROTTLE_ENTRIES: Final = 512

#: Kalit -> oxirgi yuborilgan vaqt. Modul darajasida (protsess bo'yicha global).
_THROTTLE: dict[str, datetime] = {}


def throttle_remaining(key: str) -> float:
    """Berilgan kalit bo'yicha bo'g'ish tugashiga qancha soniya qolgan.

    `0.0` — bo'g'ish yo'q, alert hoziroq yuborilishi mumkin. Monitoring va
    testlar uchun ochiq (public) funksiya.
    """
    sent_at = _THROTTLE.get(key)
    if sent_at is None:
        return 0.0
    elapsed = (utcnow() - sent_at).total_seconds()
    return max(0.0, THROTTLE_WINDOW_SECONDS - elapsed)


def reset_throttle(key: str | None = None) -> None:
    """Bo'g'ish hisobini tozalaydi.

    `key` berilsa faqat shu kalit, aks holda hammasi. Testlar va operator
    qo'lda "hozir qayta yubor" deganda ishlatiladi.
    """
    if key is None:
        _THROTTLE.clear()
    else:
        _THROTTLE.pop(key, None)


def _prune_throttle() -> None:
    """Muddati o'tgan yozuvlarni tashlaydi, lug'at kattalashsa qisqartiradi."""
    now = utcnow()
    expired = [
        key
        for key, sent_at in _THROTTLE.items()
        if (now - sent_at).total_seconds() >= THROTTLE_WINDOW_SECONDS
    ]
    for key in expired:
        _THROTTLE.pop(key, None)

    if len(_THROTTLE) <= MAX_THROTTLE_ENTRIES:
        return
    # Hamon katta — eng eskilaridan boshlab kesamiz (vaqt bo'yicha tartiblab).
    surplus = len(_THROTTLE) - MAX_THROTTLE_ENTRIES
    oldest = sorted(_THROTTLE.items(), key=lambda item: item[1])[:surplus]
    for key, _ in oldest:
        _THROTTLE.pop(key, None)


# ---------------------------------------------------------------------------
# SMTP
# ---------------------------------------------------------------------------

#: SMTP ulanishi uchun maksimal kutish (soniya). `smtplib` bloklovchi, shuning
#: uchun timeout OCHIQ berilishi shart: aks holda javob bermaydigan server
#: `asyncio.to_thread` ipini abadiy band qilib qo'yadi.
SMTP_TIMEOUT_SECONDS: Final = 15.0

#: Implicit TLS porti (`SMTP_SSL`). Qolgan portlarda `STARTTLS` sinaladi.
SMTP_SSL_PORT: Final = 465


def _safe_host(url: str | None) -> str:
    """URL'dan faqat hostni ajratadi — logga to'liq URL yozmaslik uchun.

    `ALERT_WEBHOOK_URL` (masalan Slack webhook'i) yo'l qismida MAXFIY token
    saqlaydi. To'liq URL logga tushsa, log fayli yoki Loki indeksi orqali
    kanalga yozish huquqi oshkor bo'ladi.
    """
    if not url:
        return "-"
    try:
        return urlsplit(url).hostname or "-"
    except ValueError:  # pragma: no cover - juda buzilgan URL
        return "-"


class NotificationService:
    """Operatorga xabar yetkazish: alert webhook'i va/yoki email.

    Konstruktor ataylab bo'sh — modul docstring'idagi "bog'liqlik yo'q"
    qoidasiga qara. Servis holatsiz (stateless), shuning uchun uni har
    chaqiruvda yangidan yasash arzon.
    """

    # ------------------------------------------------------------------
    # Umumiy alert
    # ------------------------------------------------------------------

    async def alert(
        self,
        title: str,
        message: str,
        *,
        level: str = AlertLevel.WARNING.value,
        context: dict[str, Any] | None = None,
        throttle_key: str | None = None,
    ) -> bool:
        """Operatorga xabar yuboradi.

        Qadamlar:

        1. **Bo'g'ish** — `throttle_key` (berilmasa `"<level>:<title>"`)
           bo'yicha oxirgi yuborishdan `THROTTLE_WINDOW_SECONDS` o'tmagan
           bo'lsa, hech narsa qilinmaydi va `False` qaytadi. Bu tekshiruv
           `NOTIFICATIONS_ENABLED` dan OLDIN turadi — shu tufayli
           o'chirilgan rejimda ham log takroriy xabar bilan to'lmaydi.
        2. **Har holda logga yoziladi** (`warning` darajasida). Log — yagona
           kafolatlangan kanal: Slack ham, SMTP ham ishlamasa, xabar baribir
           Loki/Grafana'da qoladi.
        3. `settings.NOTIFICATIONS_ENABLED=False` (development'dagi holat)
           yoki `ALERT_WEBHOOK_URL` bo'sh bo'lsa — shu bilan tugaydi,
           `False` qaytadi.
        4. Aks holda Slack-mos JSON `httpx` bilan POST qilinadi.

        Args:
            title: Qisqa sarlavha (Slack xabarining birinchi qatori).
            message: Tafsilot.
            level: `AlertLevel` qiymati yoki shunga mos matn.
            context: Qo'shimcha maydonlar — Slack `fields` ga aylanadi.
            throttle_key: Bo'g'ish kaliti. Shartnomadagi imzoga QO'SHIMCHA,
                ixtiyoriy argument: `notify_*` metodlari obyekt identifikatorini
                (worker_id, user_id...) kalitga qo'shib, har obyekt uchun
                alohida bo'g'ish oynasi olishi uchun kerak.

        Returns:
            `True` — xabar qabul qiluvchiga HTTP 2xx bilan yetib bordi.
            `False` — bo'g'ildi, o'chirilgan, sozlanmagan yoki xato bo'ldi.
            Xato HECH QACHON tashlanmaydi.
        """
        normalized = self._normalize_level(level)
        key = throttle_key or f"{normalized}:{title}"

        try:
            if throttle_remaining(key) > 0:
                logger.debug(
                    "notification.throttled",
                    alert_title=title,
                    level=normalized,
                    throttle_key=key,
                    retry_in_seconds=round(throttle_remaining(key), 1),
                )
                return False

            _prune_throttle()
            _THROTTLE[key] = utcnow()

            # Log — yagona kafolatlangan kanal (2-qadam).
            logger.warning(
                "notification.alert",
                alert_title=title,
                alert_message=message,
                level=normalized,
                context=context or {},
            )

            if not settings.NOTIFICATIONS_ENABLED:
                logger.debug(
                    "notification.disabled",
                    alert_title=title,
                    reason="NOTIFICATIONS_ENABLED=False",
                )
                return False

            target = settings.ALERT_WEBHOOK_URL
            if not target:
                logger.debug(
                    "notification.not_configured",
                    alert_title=title,
                    reason="ALERT_WEBHOOK_URL bo'sh",
                )
                return False

            return await self._post_alert(
                target,
                self._build_slack_payload(title, message, normalized, context),
                title=title,
            )
        except Exception as exc:  # alert HECH QACHON asosiy ishni yiqitmaydi
            logger.error(
                "notification.unexpected_error",
                alert_title=title,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False

    # ------------------------------------------------------------------
    # Tayyor (domenga xos) bildirishnomalar
    # ------------------------------------------------------------------

    async def notify_dlq_threshold(
        self,
        depth: int,
        *,
        user_id: uuid.UUID | str | None = None,
    ) -> None:
        """DLQ chuqurligi `settings.DLQ_ALERT_THRESHOLD` dan oshdi.

        `dlq_processor` davriy chaqiradi. Bu holat odatda tizimli nosozlikni
        bildiradi (sandbox obrazi buzilgan, tashqi API o'lgan), shuning uchun
        daraja `ERROR`, ikki baravar oshsa `CRITICAL`.

        `user_id` berilsa bo'g'ish AYNI foydalanuvchi bo'yicha alohida ishlaydi
        — bitta mijozning nosozligi boshqa mijozning alert'ini bosib
        qolmasligi uchun.
        """
        threshold = settings.DLQ_ALERT_THRESHOLD
        level = AlertLevel.CRITICAL.value if depth >= threshold * 2 else AlertLevel.ERROR.value
        context: dict[str, Any] = {"depth": depth, "threshold": threshold}
        scope = "global"
        if user_id is not None:
            context["user_id"] = str(user_id)
            scope = str(user_id)

        await self.alert(
            "DLQ chuqurligi chegaradan oshdi",
            (
                f"O'lik xatlar navbatida {depth} ta job bor "
                f"(chegara: {threshold}). Sabablarni tekshirish kerak."
            ),
            level=level,
            context=context,
            throttle_key=f"dlq_threshold:{scope}",
        )

    async def notify_worker_down(
        self,
        worker_id: str,
        *,
        last_heartbeat: datetime | None = None,
    ) -> None:
        """Worker heartbeat'i to'xtadi — lease'lari boshqa worker'ga o'tkaziladi.

        Daraja `CRITICAL`: worker yo'qolishi bajarish quvvatini kamaytiradi va
        agar hammasi o'lsa navbat o'sishdan boshqa hech narsa qilmaydi.

        Bo'g'ish kaliti worker identifikatorini o'z ichiga oladi — 10 ta worker
        birin-ketin qulasa, 10 ta alohida xabar keladi (bu kerakli xatti-harakat:
        bittasi qulashi va klaster qulashi boshqa-boshqa hodisa).
        """
        context: dict[str, Any] = {"worker_id": worker_id}
        if last_heartbeat is not None:
            context["last_heartbeat"] = isoformat(last_heartbeat)
            context["silent_seconds"] = round((utcnow() - last_heartbeat).total_seconds(), 1)

        await self.alert(
            "Worker javob bermayapti",
            (
                f"'{worker_id}' worker'idan heartbeat kelmay qoldi. "
                "Uning lease'lari muddati tugagach job'lar qayta navbatga qo'yiladi."
            ),
            level=AlertLevel.CRITICAL.value,
            context=context,
            throttle_key=f"worker_down:{worker_id}",
        )

    async def notify_queue_backlog(
        self,
        depth: int,
        *,
        priority: Priority | str | None = None,
    ) -> None:
        """Navbat o'sib ketdi — worker quvvati yetmayapti.

        Daraja `WARNING`: bu nosozlik emas, sig'im (capacity) signali —
        worker sonini oshirish kerakligini bildiradi.
        """
        context: dict[str, Any] = {"depth": depth}
        scope = "all"
        if priority is not None:
            label = Priority(priority).value if not isinstance(priority, str) else priority
            context["priority"] = label
            scope = label

        await self.alert(
            "Navbat chuqurligi o'sdi",
            (
                f"Navbatda {depth} ta job bajarilishni kutmoqda "
                f"(ustuvorlik: {scope}). Worker quvvatini oshirish kerak bo'lishi mumkin."
            ),
            level=AlertLevel.WARNING.value,
            context=context,
            throttle_key=f"queue_backlog:{scope}",
        )

    async def notify_webhook_disabled(
        self,
        webhook_url: str,
        *,
        user_id: uuid.UUID | str | None = None,
    ) -> None:
        """Webhook ketma-ket xatolar sababli AVTOMATIK o'chirildi.

        `webhook_service.deliver()` chaqiradi. Bu mijozga tegishli hodisa,
        shuning uchun daraja `WARNING` — platforma sog'lom, mijozning
        endpoint'i esa yo'q.
        """
        context: dict[str, Any] = {"webhook_url": webhook_url}
        scope = webhook_url
        if user_id is not None:
            context["user_id"] = str(user_id)
            scope = f"{user_id}:{webhook_url}"

        await self.alert(
            "Webhook avtomatik o'chirildi",
            (
                f"'{webhook_url}' manzili ketma-ket ko'p marta javob bermadi, "
                "shuning uchun webhook o'chirildi. Mijoz endpoint'ni tuzatib "
                "qaytadan yoqishi kerak."
            ),
            level=AlertLevel.WARNING.value,
            context=context,
            throttle_key=f"webhook_disabled:{scope}",
        )

    async def notify_quota_exceeded(
        self,
        user_id: uuid.UUID | str,
        *,
        plan: str,
        used: int,
        limit: int,
    ) -> None:
        """Foydalanuvchi oylik kvotasini tugatdi.

        Daraja `INFO`: bu nosozlik emas, biznes hodisasi (sotuv imkoniyati).
        Bo'g'ish foydalanuvchi bo'yicha — har mijoz uchun alohida oyna.
        """
        await self.alert(
            "Reja kvotasi tugadi",
            (
                f"Foydalanuvchi {used}/{limit} job limitiga yetdi "
                f"(reja: {plan}). Yangi job'lar rad etilmoqda."
            ),
            level=AlertLevel.INFO.value,
            context={
                "user_id": str(user_id),
                "plan": plan,
                "used": used,
                "limit": limit,
            },
            throttle_key=f"quota_exceeded:{user_id}",
        )

    # ------------------------------------------------------------------
    # Email
    # ------------------------------------------------------------------

    async def send_email(self, to: str, subject: str, body: str) -> bool:
        """Oddiy matnli email yuboradi.

        **Nega `smtplib`, `aiosmtplib` emas.** Loyihada `aiosmtplib`
        o'rnatilmagan va shartnoma bo'yicha yangi paket qo'shilmaydi. Standart
        `smtplib` bloklovchi, shuning uchun u `asyncio.to_thread` ichida
        bajariladi — event loop bloklanmaydi.

        TLS tanlovi port bo'yicha:

        * `465` (`SMTP_SSL_PORT`) — ulanishning o'zi TLS (`SMTP_SSL`);
        * boshqa port (odatda `587`) — oddiy ulanish + `STARTTLS`. Server
          `STARTTLS` ni qo'llamasa, xabar shifrlanmagan ketadi: bu ataylab,
          chunki alternativa — alert'ni UMUMAN yubormaslik.

        Returns:
            `True` — SMTP server xabarni qabul qildi. Sozlama yo'q, bildirishnoma
            o'chirilgan yoki xato bo'lsa `False`. Xato tashlanmaydi.
        """
        if not settings.NOTIFICATIONS_ENABLED:
            logger.warning(
                "notification.email_skipped",
                recipient=to,
                subject=subject,
                reason="NOTIFICATIONS_ENABLED=False",
            )
            return False

        host = settings.SMTP_HOST
        if not host:
            logger.warning(
                "notification.email_not_configured",
                recipient=to,
                subject=subject,
                reason="SMTP_HOST bo'sh",
            )
            return False

        message = EmailMessage()
        message["From"] = settings.SMTP_FROM
        message["To"] = to
        message["Subject"] = subject
        message["Date"] = utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
        message.set_content(body)

        try:
            await asyncio.to_thread(self._send_email_sync, message, host)
        except (smtplib.SMTPException, OSError) as exc:
            logger.error(
                "notification.email_failed",
                recipient=to,
                subject=subject,
                smtp_host=host,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False
        except Exception as exc:  # email HECH QACHON asosiy ishni yiqitmaydi
            logger.error(
                "notification.email_unexpected_error",
                recipient=to,
                subject=subject,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False

        logger.info("notification.email_sent", recipient=to, subject=subject)
        return True

    # ------------------------------------------------------------------
    # Ichki yordamchilar
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_level(level: str) -> str:
        """Darajani ma'lum qiymatga keltiradi; noma'lum bo'lsa `WARNING`."""
        try:
            return AlertLevel(str(level).lower()).value
        except ValueError:
            return DEFAULT_LEVEL.value

    @staticmethod
    def _build_slack_payload(
        title: str,
        message: str,
        level: str,
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Slack "Incoming Webhook" formatidagi tana.

        Ayni shu shaklni Mattermost, Discord'ning `/slack` endpoint'i va
        ko'pchilik "Slack-compatible" qabul qiluvchilar tushunadi — shuning
        uchun qabul qiluvchi uchun alohida kod yozish kerak emas.

        `text` maydoni ataylab TAKRORLANADI (attachment'dan tashqari):
        attachment'ni ko'rsatmaydigan mijozlarda (mobil bildirishnoma matni)
        xabar baribir o'qiladi.
        """
        fields = [
            {"title": str(name), "value": str(value), "short": True}
            for name, value in (context or {}).items()
        ]
        return {
            "text": f"[{level.upper()}] {settings.APP_NAME}: {title}",
            "attachments": [
                {
                    "color": LEVEL_COLORS.get(level, LEVEL_COLORS[DEFAULT_LEVEL.value]),
                    "title": title,
                    "text": message,
                    "fields": fields,
                    "footer": f"{settings.APP_NAME} · {settings.ENV}",
                    "ts": int(utcnow().timestamp()),
                }
            ],
        }

    async def _post_alert(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        title: str,
    ) -> bool:
        """Alert tanasini POST qiladi; natijani `bool` bilan qaytaradi.

        `follow_redirects=False` — alert endpoint'i qayta yo'naltirmasligi
        kerak, yo'naltirsa bu sozlama xatosi (va maxfiy token boshqa hostga
        ketib qolishi mumkin).
        """
        try:
            async with httpx.AsyncClient(
                timeout=settings.WEBHOOK_TIMEOUT_SECONDS,
                follow_redirects=False,
            ) as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            logger.error(
                "notification.send_failed",
                alert_title=title,
                target_host=_safe_host(url),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False

        delivered = 200 <= response.status_code < 300
        if not delivered:
            logger.error(
                "notification.rejected",
                alert_title=title,
                target_host=_safe_host(url),
                status_code=response.status_code,
            )
        return delivered

    @staticmethod
    def _send_email_sync(message: EmailMessage, host: str) -> None:
        """Bloklovchi SMTP yuborish — `asyncio.to_thread` ichida chaqiriladi."""
        port = settings.SMTP_PORT
        client: smtplib.SMTP
        if port == SMTP_SSL_PORT:
            client = smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT_SECONDS)
        else:
            client = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SECONDS)

        try:
            client.ehlo()
            if port != SMTP_SSL_PORT:
                try:
                    client.starttls()
                    client.ehlo()
                except smtplib.SMTPException:
                    # Server STARTTLS ni qo'llamaydi — shifrlanmagan davom etamiz
                    # (alert'ni umuman yubormaslikdan afzal), lekin ko'rinib turadi.
                    logger.warning(
                        "notification.smtp_no_starttls",
                        smtp_host=host,
                        smtp_port=port,
                    )
            if settings.SMTP_USER:
                client.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
            client.send_message(message)
        finally:
            try:
                client.quit()
            except smtplib.SMTPException:  # pragma: no cover - yopishdagi xato muhim emas
                client.close()


__all__ = [
    "DEFAULT_LEVEL",
    "LEVEL_COLORS",
    "MAX_THROTTLE_ENTRIES",
    "SMTP_SSL_PORT",
    "SMTP_TIMEOUT_SECONDS",
    "THROTTLE_WINDOW_SECONDS",
    "AlertLevel",
    "NotificationService",
    "reset_throttle",
    "throttle_remaining",
]
