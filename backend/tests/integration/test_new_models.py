"""Durabl — ikkinchi migratsiyada qo'shilgan 6 jadvalning DB testlari.

## Nega bu testlar kerak

Bu yerdagi modellarning hech biri hali servis yoki endpoint bilan
qoplanmagan (ular Faza 1B/1C da yoziladi), ya'ni **DB darajasidagi
kafolatlar hozir hech qaerda tekshirilmaydi**. Aynan shu kafolatlar
keyingi barcha kod uchun poydevor:

* **`uq_schedule_runs_schedule_id_scheduled_for`** — bitta jadval bitta
  daqiqa uchun ikki marta ishga tushmasligi. Scheduler klaster bo'yicha
  yakka, lekin deploy paytida qisqa oynada ikki nusxa ishlashi mumkin,
  shuning uchun yakkalik DB'da ham qotirilgan.
* **`uq_schedules_user_id_name`** — nom bo'yicha chalkashlik bo'lmasligi.
* **`ON DELETE` yo'nalishlari** — qaysi yozuv foydalanuvchi bilan
  o'chadi (`CASCADE`), qaysi biri QOLADI (`SET NULL`). `login_events`
  uchun bu xavfsizlik talabi: hisob o'chirilsa jurnal yo'qolmasligi
  kerak.
* **2FA ustunlarining mustaqilligi** — `totp_secret` to'ldirilgan,
  lekin `two_factor_enabled_at` bo'sh bo'lishi MUMKIN (sozlash
  boshlangan, tasdiqlanmagan). Shuning uchun "2FA yoqilganmi?" savoliga
  `has_two_factor` javob beradi, `totp_secret is not None` emas.

## `foreign_keys` pragmasi haqida

`tests/conftest.py` dagi `test_engine` fixture'i SQLite uchun
`PRAGMA foreign_keys=ON` ni yoqadi — ya'ni `ON DELETE CASCADE` va
`SET NULL` bu testlarda HAQIQATAN bajariladi. Busiz SQLite foreign key
cheklovlarini butunlay e'tiborsiz qoldirardi va testlar yolg'on
o'tardi.

## Nega `flush()` emas, `commit()`

Bir qator testlar foydalanuvchini o'chirib, `CASCADE` natijasini
o'qiydi. `flush()` dan keyin ORM identity map'ida o'chirilgan bolalar
hamon qoladi, shuning uchun `commit()` + `expire_all()` ishlatiladi —
keyingi o'qish DB'dan yangi haqiqatni oladi.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from app.constants import (
    DeviceType,
    LoginMethod,
    LoginResult,
    NotificationKind,
    NotificationSeverity,
    ScheduleRunStatus,
    ScheduleStatus,
)
from app.models import (
    LoginEvent,
    Notification,
    RecoveryCode,
    Schedule,
    ScheduleRun,
    User,
    UserSession,
)
from app.utils.time_utils import utcnow
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    make_login_event,
    make_notification,
    make_recovery_code,
    make_schedule,
    make_schedule_run,
    make_session,
)

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from app.models import Job

# ---------------------------------------------------------------------------
# schedules
# ---------------------------------------------------------------------------


async def test_jadval_saqlanadi_va_standart_qiymatlar_qollanadi(
    db_session: AsyncSession, user: User
) -> None:
    """Jadval yoziladi; server standartlari (`status`, `timezone`) qo'llanadi."""
    schedule = make_schedule(user_id=user.id, name="nightly-report")
    db_session.add(schedule)
    await db_session.flush()

    assert schedule.status is ScheduleStatus.ACTIVE
    assert schedule.timezone == "UTC"
    assert schedule.allow_overlap is False
    assert schedule.consecutive_failures == 0
    assert schedule.is_runnable is True
    assert schedule.is_auto_disabled is False
    #: Hali ishga tushmagan — ulush hisoblanmaydi
    assert schedule.success_rate is None


async def test_bir_foydalanuvchida_bir_xil_nomli_jadval_YOZILMAYDI(
    db_session: AsyncSession, user: User
) -> None:
    """`uq_schedules_user_id_name` — nom foydalanuvchi ichida yakka."""
    db_session.add(make_schedule(user_id=user.id, name="daily"))
    await db_session.flush()

    db_session.add(make_schedule(user_id=user.id, name="daily"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_turli_foydalanuvchilarda_bir_xil_nom_MUMKIN(
    db_session: AsyncSession, user: User, other_user: User
) -> None:
    """Yakkalik faqat foydalanuvchi ichida — global emas."""
    db_session.add(make_schedule(user_id=user.id, name="daily"))
    db_session.add(make_schedule(user_id=other_user.id, name="daily"))
    await db_session.flush()

    total = await db_session.scalar(select(func.count()).select_from(Schedule))
    assert total == 2


async def test_ochirilgan_jadval_ishga_tushmaydi(db_session: AsyncSession, user: User) -> None:
    """Yumshoq o'chirish `is_runnable` ni `False` qiladi."""
    schedule = make_schedule(user_id=user.id, deleted_at=utcnow())
    db_session.add(schedule)
    await db_session.flush()

    assert schedule.is_deleted is True
    assert schedule.is_runnable is False


async def test_muvaffaqiyat_ulushi_hisoblanadi(db_session: AsyncSession, user: User) -> None:
    """10 ta ishga tushish, 2 tasi yiqilgan -> 0.8."""
    schedule = make_schedule(user_id=user.id, total_runs=10, failed_runs=2)
    db_session.add(schedule)
    await db_session.flush()

    assert schedule.success_rate == pytest.approx(0.8)


async def test_foydalanuvchi_ochirilsa_jadvallari_ham_ochadi(
    db_session: AsyncSession, user: User
) -> None:
    """`schedules.user_id` -> `ON DELETE CASCADE`."""
    db_session.add(make_schedule(user_id=user.id))
    await db_session.commit()

    await db_session.delete(user)
    await db_session.commit()
    db_session.expire_all()

    total = await db_session.scalar(select(func.count()).select_from(Schedule))
    assert total == 0


# ---------------------------------------------------------------------------
# schedule_runs
# ---------------------------------------------------------------------------


async def test_bir_xil_daqiqa_uchun_ikkinchi_ishga_tushish_YOZILMAYDI(
    db_session: AsyncSession, user: User
) -> None:
    """`uq_schedule_runs_schedule_id_scheduled_for` — ikkilanishga qarshi.

    Bu testning maqsadi — deploy oynasida ikki scheduler bir xil
    daqiqani olib, ikki marta job yaratishiga DB yo'l qo'ymasligi.
    """
    schedule = make_schedule(user_id=user.id)
    db_session.add(schedule)
    await db_session.flush()

    moment = utcnow()
    db_session.add(make_schedule_run(schedule_id=schedule.id, scheduled_for=moment))
    await db_session.flush()

    db_session.add(make_schedule_run(schedule_id=schedule.id, scheduled_for=moment))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_otkazib_yuborilgan_ishga_tushish_yoziladi(
    db_session: AsyncSession, user: User
) -> None:
    """`SKIPPED` — job yaratilmagan, lekin sabab bilan yozuv qolgan."""
    schedule = make_schedule(user_id=user.id, allow_overlap=False)
    db_session.add(schedule)
    await db_session.flush()

    run = make_schedule_run(
        schedule_id=schedule.id,
        status=ScheduleRunStatus.SKIPPED,
        skip_reason="previous run still active",
        started_at=None,
    )
    db_session.add(run)
    await db_session.flush()

    assert run.was_skipped is True
    assert run.job_id is None
    #: O'tkazib yuborilgan — kechikish o'lchanmaydi
    assert run.delay_seconds is None


async def test_kechikish_rejadan_hisoblanadi(db_session: AsyncSession, user: User) -> None:
    """`delay_seconds` = `started_at - scheduled_for`, `created_at` EMAS."""
    schedule = make_schedule(user_id=user.id)
    db_session.add(schedule)
    await db_session.flush()

    planned = utcnow()
    run = make_schedule_run(
        schedule_id=schedule.id,
        scheduled_for=planned,
        started_at=planned + timedelta(seconds=12),
    )
    db_session.add(run)
    await db_session.flush()

    assert run.delay_seconds == pytest.approx(12.0)


async def test_jadval_ochirilsa_ishga_tushishlari_ham_ochadi(
    db_session: AsyncSession, user: User
) -> None:
    """`schedule_runs.schedule_id` -> `ON DELETE CASCADE`."""
    schedule = make_schedule(user_id=user.id)
    db_session.add(schedule)
    await db_session.flush()
    db_session.add(make_schedule_run(schedule_id=schedule.id))
    await db_session.commit()

    await db_session.delete(schedule)
    await db_session.commit()
    db_session.expire_all()

    total = await db_session.scalar(select(func.count()).select_from(ScheduleRun))
    assert total == 0


async def test_job_ochirilsa_ishga_tushish_yozuvi_QOLADI(
    db_session: AsyncSession, user: User, job_factory: Callable[..., Awaitable[Job]]
) -> None:
    """`schedule_runs.job_id` -> `SET NULL`, ya'ni tarix saqlanadi.

    Bu ataylab `CASCADE` emas: job'lar vaqt o'tib tozalanadi, lekin
    "shu jadval 14:00 da muvaffaqiyatli ishladi" ma'lumoti qolishi kerak.
    """
    job = await job_factory(owner=user)
    schedule = make_schedule(user_id=user.id)
    db_session.add(schedule)
    await db_session.flush()
    run = make_schedule_run(schedule_id=schedule.id, job_id=job.id)
    db_session.add(run)
    await db_session.commit()
    #: ID ni OLDIN olib qo'yamiz: `expire_all()` dan keyin `run.id` ga
    #: murojaat qilish sinxron refresh'ni qo'zg'atadi va async sessiyada
    #: `MissingGreenlet` beradi.
    run_id = run.id

    await db_session.delete(job)
    await db_session.commit()
    db_session.expire_all()

    survived = await db_session.get(ScheduleRun, run_id)
    assert survived is not None
    assert survived.job_id is None
    assert survived.status is ScheduleRunStatus.SUCCEEDED


# ---------------------------------------------------------------------------
# user_sessions
# ---------------------------------------------------------------------------


async def test_sessiya_amal_qiladi_va_bekor_qilinadi(db_session: AsyncSession, user: User) -> None:
    """`is_valid()` bekor qilish va muddat tugashini birga tekshiradi."""
    now = utcnow()
    session = make_session(user_id=user.id, expires_at=now + timedelta(days=7))
    db_session.add(session)
    await db_session.flush()

    assert session.is_valid(now=now) is True
    assert session.is_revoked is False

    session.revoked_at = now
    await db_session.flush()

    assert session.is_valid(now=now) is False
    assert session.is_revoked is True


async def test_muddati_tugagan_sessiya_bekor_qilinmagan_bolsa_ham_ishlamaydi(
    db_session: AsyncSession, user: User
) -> None:
    """Muddat tugashi `revoked_at` dan mustaqil ishlaydi."""
    now = utcnow()
    session = make_session(user_id=user.id, expires_at=now - timedelta(seconds=1))
    db_session.add(session)
    await db_session.flush()

    assert session.revoked_at is None
    assert session.is_valid(now=now) is False


async def test_bir_xil_token_hash_ikki_sessiyaga_YOZILMAYDI(
    db_session: AsyncSession, user: User, other_user: User
) -> None:
    """`token_hash` GLOBAL unique — bitta token bitta sessiyaga tegishli."""
    shared = make_session(user_id=user.id).token_hash
    db_session.add(make_session(user_id=user.id, token_hash=shared))
    await db_session.flush()

    db_session.add(make_session(user_id=other_user.id, token_hash=shared))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_qurilma_nomi_yetishmagan_malumotda_ham_ishlaydi(
    db_session: AsyncSession, user: User
) -> None:
    """`device_label` — brauzer/OS aniqlanmasa ham istisno tashlamaydi."""
    bare = make_session(user_id=user.id, browser=None, os=None, device_type=DeviceType.API)
    db_session.add(bare)
    await db_session.flush()

    assert bare.device_label == "Unknown device"
    assert make_session(browser="Safari", os=None).device_label == "Safari"


async def test_foydalanuvchi_ochirilsa_sessiyalari_ham_ochadi(
    db_session: AsyncSession, user: User
) -> None:
    """`user_sessions.user_id` -> `ON DELETE CASCADE`."""
    db_session.add(make_session(user_id=user.id))
    await db_session.commit()

    await db_session.delete(user)
    await db_session.commit()
    db_session.expire_all()

    total = await db_session.scalar(select(func.count()).select_from(UserSession))
    assert total == 0


# ---------------------------------------------------------------------------
# login_events
# ---------------------------------------------------------------------------


async def test_muvaffaqiyatsiz_urinish_ham_yoziladi(db_session: AsyncSession, user: User) -> None:
    """Noto'g'ri parol urinishi jurnalga tushadi."""
    event = make_login_event(
        user_id=user.id,
        email=user.email,
        result=LoginResult.FAILED_PASSWORD,
        detail="invalid credentials",
    )
    db_session.add(event)
    await db_session.flush()

    assert event.succeeded is False
    assert event.result is LoginResult.FAILED_PASSWORD


async def test_mavjud_bolmagan_foydalanuvchi_uchun_ham_yoziladi(
    db_session: AsyncSession,
) -> None:
    """`user_id` `NULL` bo'lishi mumkin — email baribir saqlanadi."""
    event = make_login_event(
        user_id=None,
        email="hujumchi@example.com",
        result=LoginResult.FAILED_PASSWORD,
    )
    db_session.add(event)
    await db_session.flush()

    assert event.user_id is None
    assert event.email == "hujumchi@example.com"


async def test_foydalanuvchi_ochirilsa_kirish_jurnali_QOLADI(
    db_session: AsyncSession, user: User
) -> None:
    """`login_events.user_id` -> `SET NULL`, cascade EMAS.

    Xavfsizlik talabi: buzilgan hisob o'chirilganda ham "kim, qachon,
    qaysi IP'dan kirdi" ma'lumoti saqlanishi kerak.
    """
    email = user.email
    db_session.add(make_login_event(user_id=user.id, email=email))
    await db_session.commit()

    await db_session.delete(user)
    await db_session.commit()
    db_session.expire_all()

    rows = (await db_session.scalars(select(LoginEvent))).all()
    assert len(rows) == 1
    assert rows[0].user_id is None
    assert rows[0].email == email


async def test_2fa_urinishi_usul_bilan_yoziladi(db_session: AsyncSession, user: User) -> None:
    """`method` parol va parol+2FA ni ajratadi."""
    event = make_login_event(
        user_id=user.id,
        result=LoginResult.FAILED_2FA,
        method=LoginMethod.PASSWORD_2FA,
    )
    db_session.add(event)
    await db_session.flush()

    assert event.method is LoginMethod.PASSWORD_2FA
    assert event.succeeded is False


# ---------------------------------------------------------------------------
# recovery_codes va 2FA ustunlari
# ---------------------------------------------------------------------------


async def test_tiklash_kodi_ishlatilganda_belgilanadi(db_session: AsyncSession, user: User) -> None:
    """Kod o'chirilmaydi — `used_at` va IP yoziladi."""
    code = make_recovery_code(user_id=user.id)
    db_session.add(code)
    await db_session.flush()
    assert code.is_used is False

    code.used_at = utcnow()
    code.used_from_ip = "203.0.113.99"
    await db_session.flush()

    assert code.is_used is True
    assert code.used_from_ip == "203.0.113.99"


async def test_bir_foydalanuvchida_bir_xil_kod_hashi_YOZILMAYDI(
    db_session: AsyncSession, user: User
) -> None:
    """`uq_recovery_codes_user_id_code_hash` — takrorlanishga qarshi."""
    shared = make_recovery_code(user_id=user.id).code_hash
    db_session.add(make_recovery_code(user_id=user.id, code_hash=shared))
    await db_session.flush()

    db_session.add(make_recovery_code(user_id=user.id, code_hash=shared))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_2fa_sozlash_boshlangan_lekin_yoqilmagan_holat(
    db_session: AsyncSession, user: User
) -> None:
    """`totp_secret` bor, `two_factor_enabled_at` yo'q -> 2FA YOQILMAGAN.

    Bu holat haqiqiy: mijoz QR kodni oldi, lekin birinchi kodni
    tasdiqlamadi. Shu paytda login 2FA so'ramasligi kerak.
    """
    user.totp_secret = "JBSWY3DPEHPK3PXP"
    await db_session.flush()

    assert user.totp_secret is not None
    assert user.two_factor_enabled_at is None
    assert user.has_two_factor is False

    user.two_factor_enabled_at = utcnow()
    await db_session.flush()
    assert user.has_two_factor is True


async def test_foydalanuvchi_ochirilsa_tiklash_kodlari_ham_ochadi(
    db_session: AsyncSession, user: User
) -> None:
    """`recovery_codes.user_id` -> `ON DELETE CASCADE`."""
    db_session.add(make_recovery_code(user_id=user.id))
    await db_session.commit()

    await db_session.delete(user)
    await db_session.commit()
    db_session.expire_all()

    total = await db_session.scalar(select(func.count()).select_from(RecoveryCode))
    assert total == 0


# ---------------------------------------------------------------------------
# notifications
# ---------------------------------------------------------------------------


async def test_bildirishnoma_oqilmagan_holda_yaratiladi(
    db_session: AsyncSession, user: User
) -> None:
    """`read_at` — o'qilganlikning YAGONA manbasi."""
    notification = make_notification(user_id=user.id)
    db_session.add(notification)
    await db_session.flush()

    assert notification.is_read is False
    assert notification.has_link is False

    notification.read_at = utcnow()
    await db_session.flush()
    assert notification.is_read is True


async def test_manba_havolasi_foreign_key_BOLMAGANI_uchun_ozgarmaydi(
    db_session: AsyncSession, user: User
) -> None:
    """`source_id` mavjud bo'lmagan yozuvga ishora qilishi MUMKIN.

    Bu ataylab: manba (job, webhook) o'chirilganda bildirishnoma
    yo'qolmasligi kerak, shuning uchun foreign key qo'yilmagan.
    """
    ghost = uuid.uuid4()
    notification = make_notification(
        user_id=user.id,
        kind=NotificationKind.DLQ_ENTRY,
        severity=NotificationSeverity.CRITICAL,
        source_type="job",
        source_id=ghost,
        href=f"/jobs/{ghost}",
    )
    db_session.add(notification)
    await db_session.flush()

    assert notification.source_id == ghost
    assert notification.has_link is True


async def test_oqilmaganlar_soni_sanaladi(db_session: AsyncSession, user: User) -> None:
    """Qo'ng'iroqdagi hisoblagich uchun asosiy so'rov."""
    db_session.add_all(
        [
            make_notification(user_id=user.id),
            make_notification(user_id=user.id),
            make_notification(user_id=user.id, read_at=utcnow()),
        ]
    )
    await db_session.flush()

    unread = await db_session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    assert unread == 2


async def test_foydalanuvchi_ochirilsa_bildirishnomalari_ham_ochadi(
    db_session: AsyncSession, user: User
) -> None:
    """`notifications.user_id` -> `ON DELETE CASCADE`."""
    db_session.add(make_notification(user_id=user.id))
    await db_session.commit()

    await db_session.delete(user)
    await db_session.commit()
    db_session.expire_all()

    total = await db_session.scalar(select(func.count()).select_from(Notification))
    assert total == 0
