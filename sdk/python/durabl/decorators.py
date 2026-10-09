"""`@durabl.task` dekoratori va global `durabl` obyekti.

Dekorator oddiy Python funksiyasini Durabl'da bajariladigan job'ga aylantiradi:

    from durabl import durabl

    durabl.configure(api_key="durabl_xxx")

    @durabl.task(runtime="python", timeout=30, retries=3)
    def process_image(url):
        import urllib.request
        return len(urllib.request.urlopen(url).read())

    job = process_image.delay("https://example.com/img.jpg")
    result = job.wait()
    print(result.value())        # funksiya qaytargan qiymat
    print(process_image.run(url))  # xohlasa — lokal bajarish

Qanday ishlaydi:

1. `inspect.getsource` bilan funksiya manbasi olinadi va `textwrap.dedent`
   bilan chap bo'shliqlar olib tashlanadi;
2. dekorator qatorlari (`@...`) kesib tashlanadi — aks holda sandbox ichida
   `durabl` paketi kerak bo'lib qolardi;
3. manbaga "yuklovchi" (loader) qo'shiladi: u `payload.json`dan argumentlarni
   o'qiydi, funksiyani chaqiradi va natijani stdout'ga
   `{"__durabl_result__": <qiymat>}` ko'rinishida chiqaradi;
4. argumentlar backend'ga `payload={"args": [...], "kwargs": {...}}` sifatida
   yuboriladi (sandbox ichida `payload.json` fayliga tushadi).
"""

from __future__ import annotations

import functools
import inspect
import re
import textwrap
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import suppress
from typing import Any

from .client import AsyncDurablClient, DurablClient
from .config import DurablConfig
from .exceptions import DurablConfigError, JobFailedError, ValidationError
from .job import RESULT_MARKER, AsyncJobHandle, JobHandle, JobResult

#: Sandbox ichida payload shu fayldan o'qiladi
#: (backend `app/constants.py:SANDBOX_PAYLOAD_FILENAME` bilan bir xil).
PAYLOAD_FILENAME = "payload.json"
#: Payload fayli bo'lmasa — shu muhit o'zgaruvchisi tekshiriladi.
PAYLOAD_ENV_VAR = "DURABL_PAYLOAD"

#: `def` yoki `async def` qatorini topish uchun shablon.
_DEF_PATTERN = re.compile(r"^(async\s+)?def\s+\w+\s*\(")


def strip_decorators(source: str) -> str:
    """Funksiya manbasidan dekorator qatorlarini olib tashlaydi.

    `inspect.getsource` dekoratorlar bilan birga qaytaradi, lekin sandbox
    ichida `@durabl.task` mavjud bo'lmaydi. Shuning uchun birinchi
    `def`/`async def` qatoridan oldingi hamma narsa kesiladi. Dekorator bir
    necha qatorga yozilgan bo'lsa ham (`@durabl.task(\\n  timeout=5,\\n)`)
    to'g'ri ishlaydi.
    """
    dedented = textwrap.dedent(source)
    lines = dedented.splitlines()
    for index, line in enumerate(lines):
        if _DEF_PATTERN.match(line.strip()):
            return "\n".join(lines[index:]).rstrip() + "\n"
    # Dekorator topilmadi — manbani o'zgartirmasdan qaytaramiz.
    return dedented.rstrip() + "\n"


def build_task_code(func: Callable[..., Any], source: str | None = None) -> str:
    """Funksiya uchun sandbox'da bajariladigan to'liq kodni yasaydi.

    Argumentlar:
        func: Dekoratsiya qilingan funksiya.
        source: Manba kod (berilmasa `inspect.getsource` bilan olinadi).

    Qaytaradi:
        Mustaqil ishlaydigan Python skript matni.
    """
    if source is None:
        try:
            source = inspect.getsource(func)
        except (OSError, TypeError) as exc:  # interaktiv REPL, exec() va h.k.
            raise ValidationError(
                message=(
                    f"`{getattr(func, '__name__', func)}` funksiyasining manba kodi o'qilmadi. "
                    "Dekorator faqat fayldagi funksiyalar uchun ishlaydi — "
                    "interaktiv rejimda `client.submit(code=...)` dan foydalaning."
                )
            ) from exc

    body = strip_decorators(source)
    name = func.__name__
    loader = textwrap.dedent(
        f"""
        # --- Durabl yuklovchisi (avtomatik qo'shilgan) ---
        import json, os

        _raw = None
        try:
            with open({PAYLOAD_FILENAME!r}, "r", encoding="utf-8") as _fh:
                _raw = _fh.read()
        except OSError:
            _raw = os.environ.get({PAYLOAD_ENV_VAR!r})

        _payload = json.loads(_raw) if _raw else {{}}
        _args = _payload.get("args") or []
        _kwargs = _payload.get("kwargs") or {{}}
        _result = {name}(*_args, **_kwargs)
        print(json.dumps({{{RESULT_MARKER!r}: _result}}, default=str))
        """
    ).strip()
    return f"{body}\n\n{loader}\n"


def build_payload(args: Sequence[Any], kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Argumentlarni backend uchun payload shakliga keltiradi."""
    return {"args": list(args), "kwargs": dict(kwargs)}


class DurablTask:
    """`@durabl.task` qaytaradigan obyekt.

    Asl funksiyaning `__name__`, `__doc__` va boshqa metama'lumotlari
    `functools.wraps` orqali saqlanadi, shuning uchun hujjat vositalari va
    xato xabarlari o'zgarmaydi.

    Metodlar:
        `delay(*args, **kwargs)` — Durabl'ga yuboradi, `JobHandle` qaytaradi;
        `run(*args, **kwargs)`   — funksiyani LOKAL bajaradi (test uchun qulay);
        `call(*args, **kwargs)`  — yuboradi, kutadi va qaytarilgan qiymatni beradi;
        `code()`                 — yuboriladigan kodni ko'rsatadi (debug uchun);
        `options(...)`           — sozlamalari o'zgartirilgan yangi nusxa.
    """

    def __init__(
        self,
        func: Callable[..., Any],
        *,
        runtime: str = "python",
        timeout: int = 30,
        retries: int = 3,
        priority: str = "normal",
        env_vars: Mapping[str, str] | None = None,
        tags: Iterable[str] | None = None,
        memory_mb: int | None = None,
        cpus: float | None = None,
        client: DurablClient | None = None,
        app: Durabl | None = None,
    ) -> None:
        if not callable(func):
            raise ValidationError(message="`@durabl.task` faqat funksiyaga qo'llanadi")
        self.func = func
        self.runtime = str(runtime)
        self.timeout = int(timeout)
        self.retries = int(retries)
        self.priority = str(priority)
        self.env_vars = dict(env_vars) if env_vars else None
        self.tags = list(tags) if tags else None
        self.memory_mb = memory_mb
        self.cpus = cpus
        self._client = client
        self._app = app
        functools.update_wrapper(self, func)

    # ------------------------------------------------------------------
    # Kod generatsiyasi
    # ------------------------------------------------------------------

    def code(self) -> str:
        """Sandbox'da bajariladigan to'liq kodni qaytaradi."""
        return build_task_code(self.func)

    #: `build_code` — `code()` uchun tushunarli taxallus.
    build_code = code

    # ------------------------------------------------------------------
    # Bajarish
    # ------------------------------------------------------------------

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Funksiyani LOKAL bajaradi (Durabl'ga so'rov yuborilmaydi)."""
        return self.func(*args, **kwargs)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Dekoratsiyalangan funksiyani oddiy chaqirish — lokal bajarish.

        Shu sababli dekorator qo'shilgandan keyin ham mavjud kod ishlashda
        davom etadi; serverda bajarish uchun `delay()` ishlatiladi.
        """
        return self.run(*args, **kwargs)

    def delay(self, *args: Any, **kwargs: Any) -> JobHandle:
        """Funksiyani Durabl'ga yuboradi va `JobHandle` qaytaradi."""
        return self.apply_async(args, kwargs)

    def apply_async(
        self,
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
        **options: Any,
    ) -> JobHandle:
        """`delay()`ning to'liq varianti — qo'shimcha sozlamalar bilan.

        Masalan: `task.apply_async((1, 2), idempotency_key="abc", priority="high")`.
        """
        client = self._resolve_client()
        payload = build_payload(args, kwargs or {})
        return client.submit(self.code(), self.runtime, **self._submit_kwargs(payload, options))

    def call(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Yuboradi, tugashini kutadi va funksiya qaytargan qiymatni beradi.

        Job muvaffaqiyatsiz tugasa `JobFailedError` tashlanadi — oddiy
        funksiya chaqiruvi kabi tuyulishi uchun.
        """
        wait_timeout = float(kwargs.pop("__wait_timeout__", self.timeout * (self.retries + 1) + 30))
        handle = self.delay(*args, **kwargs)
        result = handle.wait(timeout=wait_timeout)
        if not result.ok:
            raise JobFailedError(handle.job, result=result)
        return result.value()

    # ------------------------------------------------------------------
    # Yordamchilar
    # ------------------------------------------------------------------

    def options(self, **changes: Any) -> DurablTask:
        """Sozlamalari o'zgartirilgan yangi `DurablTask` qaytaradi."""
        base: dict[str, Any] = {
            "runtime": self.runtime,
            "timeout": self.timeout,
            "retries": self.retries,
            "priority": self.priority,
            "env_vars": self.env_vars,
            "tags": self.tags,
            "memory_mb": self.memory_mb,
            "cpus": self.cpus,
            "client": self._client,
            "app": self._app,
        }
        base.update(changes)
        return DurablTask(self.func, **base)

    def _submit_kwargs(
        self, payload: Mapping[str, Any], options: Mapping[str, Any]
    ) -> dict[str, Any]:
        """`client.submit()` uchun nomlangan argumentlarni yasaydi."""
        kwargs: dict[str, Any] = {
            "payload": dict(payload),
            "timeout": self.timeout,
            "max_retries": self.retries,
            "priority": self.priority,
            "env_vars": self.env_vars,
            "tags": self.tags,
            "memory_mb": self.memory_mb,
            "cpus": self.cpus,
        }
        kwargs.update(options)
        return kwargs

    def _resolve_client(self) -> DurablClient:
        """Ishlatiladigan mijozni aniqlaydi: avval o'ziniki, keyin global."""
        if self._client is not None:
            return self._client
        app = self._app or durabl
        return app.client

    def __repr__(self) -> str:
        return (
            f"DurablTask({self.func.__name__}, runtime={self.runtime!r}, "
            f"timeout={self.timeout}, retries={self.retries})"
        )


class AsyncDurablTask(DurablTask):
    """Asinxron mijoz bilan ishlaydigan vazifa (`durabl.async_task`).

    `delay()` korutina qaytaradi, shuning uchun `await` bilan chaqiriladi:

        handle = await task.delay(1, 2)
        result = await handle.wait()
    """

    def __init__(
        self, func: Callable[..., Any], *, client: AsyncDurablClient, **options: Any
    ) -> None:
        super().__init__(func, **options)
        self._async_client = client

    async def delay(self, *args: Any, **kwargs: Any) -> AsyncJobHandle:  # type: ignore[override]
        """Funksiyani asinxron yuboradi."""
        return await self.apply_async(args, kwargs)

    async def apply_async(  # type: ignore[override]
        self,
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
        **options: Any,
    ) -> AsyncJobHandle:
        """`delay()`ning to'liq asinxron varianti."""
        payload = build_payload(args, kwargs or {})
        return await self._async_client.submit(
            self.code(), self.runtime, **self._submit_kwargs(payload, options)
        )

    async def call(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        """Yuboradi, kutadi va qiymatni qaytaradi (asinxron)."""
        wait_timeout = float(kwargs.pop("__wait_timeout__", self.timeout * (self.retries + 1) + 30))
        handle = await self.delay(*args, **kwargs)
        result = await handle.wait(timeout=wait_timeout)
        if not result.ok:
            raise JobFailedError(handle.job, result=result)
        return result.value()


class Durabl:
    """Global kirish nuqtasi: `durabl.configure()`, `durabl.task()`, `durabl.client`.

    Mijoz dangasa (lazy) yaratiladi — `durabl.client`ga birinchi murojaatda.
    Shu sababli `@durabl.task` dekoratorini modul yuklanishida ishlatish
    mumkin, API kalit esa keyinroq (`configure()` yoki `DURABL_API_KEY`)
    berilishi mumkin.
    """

    def __init__(self, config: DurablConfig | None = None) -> None:
        self._config = config
        self._client: DurablClient | None = None

    # ------------------------------------------------------------------
    # Sozlash
    # ------------------------------------------------------------------

    def configure(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
        retry_backoff: float | None = None,
        **extra: Any,
    ) -> DurablConfig:
        """Global sozlamani o'rnatadi va mavjud mijozni qayta yaratadi.

        Qayta chaqirilsa, oldingi mijoz yopiladi — ulanishlar oqib ketmaydi.
        """
        overrides: dict[str, Any] = {
            "api_key": api_key,
            "base_url": base_url,
            "timeout": timeout,
            "max_retries": max_retries,
            "retry_backoff": retry_backoff,
            **extra,
        }
        overrides = {key: val for key, val in overrides.items() if val is not None}
        self._config = (
            self._config.merge(**overrides)
            if self._config is not None
            else DurablConfig(**overrides)
        )
        self._close_client()
        return self._config

    @property
    def config(self) -> DurablConfig:
        """Joriy sozlama (berilmagan bo'lsa muhitdan yasaladi)."""
        if self._config is None:
            self._config = DurablConfig()
        return self._config

    @property
    def client(self) -> DurablClient:
        """Global sinxron mijoz (birinchi murojaatda yaratiladi)."""
        if self._client is None:
            try:
                self._client = DurablClient(config=self.config)
            except DurablConfigError as exc:
                raise DurablConfigError(
                    f"{exc} Masalan: durabl.configure(api_key='durabl_...')"
                ) from exc
        return self._client

    def set_client(self, client: DurablClient | None) -> None:
        """Mijozni bevosita o'rnatadi (testlar va maxsus holatlar uchun)."""
        self._close_client()
        self._client = client

    def reset(self) -> None:
        """Sozlama va mijozni tozalaydi (asosan testlar uchun)."""
        self._close_client()
        self._config = None

    def close(self) -> None:
        """Global mijozni yopadi."""
        self._close_client()

    def _close_client(self) -> None:
        """Mavjud mijozni ehtiyotkorlik bilan yopadi."""
        client = self._client
        self._client = None
        if client is not None:
            # Yopishdagi xato asosiy ish oqimini buzmasligi kerak.
            with suppress(Exception):
                client.close()

    # ------------------------------------------------------------------
    # Dekorator
    # ------------------------------------------------------------------

    def task(
        self,
        func: Callable[..., Any] | None = None,
        *,
        runtime: str = "python",
        timeout: int = 30,
        retries: int = 3,
        priority: str = "normal",
        env_vars: Mapping[str, str] | None = None,
        tags: Iterable[str] | None = None,
        memory_mb: int | None = None,
        cpus: float | None = None,
        client: DurablClient | None = None,
    ) -> Any:
        """Funksiyani Durabl vazifasiga aylantiradi.

        Ikki shaklda ishlaydi:

            @durabl.task
            def f(): ...

            @durabl.task(runtime="python", timeout=30, retries=3)
            def g(x): ...
        """

        def wrap(target: Callable[..., Any]) -> DurablTask:
            return DurablTask(
                target,
                runtime=runtime,
                timeout=timeout,
                retries=retries,
                priority=priority,
                env_vars=env_vars,
                tags=tags,
                memory_mb=memory_mb,
                cpus=cpus,
                client=client,
                app=self,
            )

        if func is not None:
            return wrap(func)
        return wrap

    def async_task(
        self,
        client: AsyncDurablClient,
        *,
        runtime: str = "python",
        timeout: int = 30,
        retries: int = 3,
        priority: str = "normal",
        **options: Any,
    ) -> Callable[[Callable[..., Any]], AsyncDurablTask]:
        """Asinxron mijoz bilan ishlaydigan dekorator.

        Asinxron mijoz hayot sikli chaqiruvchi tomonida boshqarilgani uchun
        u bevosita argument sifatida beriladi:

            @durabl.async_task(async_client, timeout=60)
            def heavy(x): ...
        """

        def wrap(target: Callable[..., Any]) -> AsyncDurablTask:
            return AsyncDurablTask(
                target,
                client=client,
                runtime=runtime,
                timeout=timeout,
                retries=retries,
                priority=priority,
                app=self,
                **options,
            )

        return wrap

    # ------------------------------------------------------------------
    # Qulaylik uchun qisqa yo'llar
    # ------------------------------------------------------------------

    def submit(self, code: str, runtime: str = "python", **options: Any) -> JobHandle:
        """Global mijoz orqali kod yuboradi."""
        return self.client.submit(code, runtime, **options)

    def result_of(self, job_id: str, timeout: float = 60.0) -> JobResult:
        """Global mijoz orqali job natijasini kutadi."""
        return self.client.wait_for_result(job_id, timeout=timeout)

    def __repr__(self) -> str:
        state = "ulangan" if self._client is not None else "dangasa"
        return f"Durabl(client={state})"


#: Global obyekt — `from durabl import durabl` orqali ishlatiladi.
durabl = Durabl()


def task(func: Callable[..., Any] | None = None, **options: Any) -> Any:
    """Global `durabl.task` uchun qisqa yo'l: `from durabl import task`."""
    return durabl.task(func, **options)


def configure(**options: Any) -> DurablConfig:
    """Global `durabl.configure` uchun qisqa yo'l."""
    return durabl.configure(**options)


__all__ = [
    "PAYLOAD_ENV_VAR",
    "PAYLOAD_FILENAME",
    "AsyncDurablTask",
    "Durabl",
    "DurablTask",
    "build_payload",
    "build_task_code",
    "configure",
    "durabl",
    "strip_decorators",
    "task",
]
