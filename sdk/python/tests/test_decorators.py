"""`@durabl.task` dekoratori, kod generatsiyasi va global `durabl` obyekti testlari."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from typing import Any

import httpx
import pytest
import respx

from durabl import (
    RESULT_MARKER,
    AsyncDurablClient,
    Durabl,
    DurablClient,
    DurablConfigError,
    DurablTask,
    JobFailedError,
    JobHandle,
    ValidationError,
    build_task_code,
)
from durabl.decorators import PAYLOAD_FILENAME, build_payload, strip_decorators

from .conftest import API_KEY, BASE_URL, job_payload, result_payload

JOB_ID = "11111111-1111-1111-1111-111111111111"
JOB_URL = f"/api/v1/jobs/{JOB_ID}"


@pytest.fixture
def app(client: DurablClient) -> Durabl:
    """Izolyatsiyalangan global obyekt (test mijozi bilan)."""
    instance = Durabl()
    instance.set_client(client)
    return instance


def summarize(text, repeat=1):
    """Test uchun oddiy funksiya: matnni takrorlab uzunligini qaytaradi."""
    value = text * repeat
    return {"uzunlik": len(value), "matn": value}


# ---------------------------------------------------------------------------
# Kod generatsiyasi
# ---------------------------------------------------------------------------


def test_build_task_code_dekorator_qatorini_olib_tashlaydi(app: Durabl) -> None:
    """Yasalgan kodda `@durabl.task` qolmasligi kerak."""

    @app.task(runtime="python", timeout=15, retries=1)
    def kvadrat(x: int) -> int:
        """Sonning kvadrati."""
        return x * x

    code = kvadrat.code()

    assert "@app.task" not in code
    assert "@durabl.task" not in code
    assert code.startswith("def kvadrat(x: int) -> int:")
    assert "import json, os" in code
    assert PAYLOAD_FILENAME in code
    assert RESULT_MARKER in code
    assert "_result = kvadrat(*_args, **_kwargs)" in code


def test_strip_decorators_kop_qatorli_dekoratorni_oladi() -> None:
    """Dekorator bir necha qatorga yozilgan bo'lsa ham kesiladi."""
    source = textwrap.dedent(
        '''
        @durabl.task(
            runtime="python",
            timeout=30,
        )
        async def ishla(a, b=2):
            """Izoh."""
            return a + b
        '''
    )
    stripped = strip_decorators(source)

    assert stripped.startswith("async def ishla(a, b=2):")
    assert "@durabl.task" not in stripped
    assert "return a + b" in stripped


def test_strip_decorators_dekoratorsiz_manbani_ozgartirmaydi() -> None:
    """Dekoratorsiz funksiya manbasi o'zgarmaydi."""
    source = "def f():\n    return 1\n"
    assert strip_decorators(source) == source


def test_build_task_code_ichma_ich_funksiyada_ishlaydi() -> None:
    """Funksiya boshqa funksiya ichida bo'lsa chap bo'shliqlar olib tashlanadi."""

    def ichki(a: int) -> int:
        return a + 1

    code = build_task_code(ichki)
    assert code.startswith("def ichki(a: int) -> int:")
    # Natijada sintaksis to'g'ri bo'lishi kerak.
    compile(code, "<yasalgan>", "exec")


def test_build_task_code_manba_oqilmasa_xato() -> None:
    """`exec` bilan yasalgan funksiyada manba yo'q — tushunarli xato."""
    namespace: dict[str, Any] = {}
    exec("def dinamik():\n    return 1\n", namespace)  # noqa: S102 - test uchun ataylab

    with pytest.raises(ValidationError) as excinfo:
        build_task_code(namespace["dinamik"])

    assert "manba kodi o'qilmadi" in str(excinfo.value)


def test_yasalgan_kod_haqiqatan_ishlaydi(tmp_path: Any) -> None:
    """Yasalgan kod sandbox ichida bo'lgani kabi bajariladi va natija chiqadi."""
    code = build_task_code(summarize)
    (tmp_path / "main.py").write_text(code, encoding="utf-8")
    (tmp_path / PAYLOAD_FILENAME).write_text(
        json.dumps({"args": ["ab"], "kwargs": {"repeat": 3}}), encoding="utf-8"
    )

    completed = subprocess.run(
        [sys.executable, "main.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload[RESULT_MARKER] == {"uzunlik": 6, "matn": "ababab"}


def test_yasalgan_kod_payload_faylsiz_muhitdan_oqiydi(tmp_path: Any) -> None:
    """`payload.json` bo'lmasa, payload muhit o'zgaruvchisidan olinadi."""
    code = build_task_code(summarize)
    (tmp_path / "main.py").write_text(code, encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "main.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env={
            "PATH": "/usr/bin:/bin",
            "DURABL_PAYLOAD": json.dumps({"args": ["x"], "kwargs": {}}),
        },
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload[RESULT_MARKER] == {"uzunlik": 1, "matn": "x"}


def test_build_payload_shakli() -> None:
    """Payload `{"args": [...], "kwargs": {...}}` ko'rinishida bo'ladi."""
    assert build_payload((1, "a"), {"k": True}) == {"args": [1, "a"], "kwargs": {"k": True}}
    assert build_payload((), {}) == {"args": [], "kwargs": {}}


# ---------------------------------------------------------------------------
# functools.wraps va lokal bajarish
# ---------------------------------------------------------------------------


def test_dekorator_metamalumotni_saqlaydi(app: Durabl) -> None:
    """`functools.wraps` orqali `__name__` va `__doc__` saqlanadi."""

    @app.task()
    def kop_ishla(a: int, b: int = 1) -> int:
        """Ikki sonni qo'shadi."""
        return a + b

    assert isinstance(kop_ishla, DurablTask)
    assert kop_ishla.__name__ == "kop_ishla"
    assert kop_ishla.__doc__ == "Ikki sonni qo'shadi."
    assert kop_ishla.__wrapped__ is kop_ishla.func
    assert "kop_ishla" in repr(kop_ishla)


def test_run_va_chaqiruv_lokal_bajaradi(app: Durabl) -> None:
    """`run()` va oddiy chaqiruv serverga so'rov yubormaydi."""

    @app.task()
    def qosh(a: int, b: int) -> int:
        return a + b

    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        route = router.post("/api/v1/jobs")
        assert qosh.run(2, 3) == 5
        assert qosh(2, 3) == 5

    assert not route.called


def test_task_qavssiz_ham_ishlaydi(app: Durabl) -> None:
    """`@durabl.task` (qavssiz) va `@durabl.task(...)` — ikkisi ham to'g'ri."""

    @app.task
    def birinchi() -> int:
        return 1

    @app.task(timeout=99)
    def ikkinchi() -> int:
        return 2

    assert isinstance(birinchi, DurablTask)
    assert birinchi.timeout == 30
    assert ikkinchi.timeout == 99


def test_options_yangi_nusxa_qaytaradi(app: Durabl) -> None:
    """`options()` asl vazifani o'zgartirmaydi."""

    @app.task(timeout=10, retries=1, priority="low")
    def ish() -> int:
        return 1

    boshqa = ish.options(timeout=60, priority="high")

    assert (ish.timeout, ish.priority) == (10, "low")
    assert (boshqa.timeout, boshqa.priority) == (60, "high")
    assert boshqa.retries == 1
    assert boshqa.func is ish.func


def test_notogri_obyektga_dekorator_qollanmaydi() -> None:
    """Funksiya bo'lmagan obyekt uchun xato beradi."""
    with pytest.raises(ValidationError):
        DurablTask("bu funksiya emas")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# delay / apply_async / call
# ---------------------------------------------------------------------------


def test_delay_kod_va_payloadni_yuboradi(app: Durabl) -> None:
    """`delay()` kodni va argumentlarni backend'ga yuboradi."""

    @app.task(runtime="python", timeout=45, retries=2, priority="high", tags=["dekorator"])
    def kopaytir(a: int, b: int = 2) -> int:
        return a * b

    with respx.mock(base_url=BASE_URL) as router:
        route = router.post("/api/v1/jobs").mock(
            return_value=httpx.Response(201, json=job_payload(status="queued"))
        )
        handle = kopaytir.delay(3, b=4)

    body = json.loads(route.calls.last.request.content)
    assert isinstance(handle, JobHandle)
    assert handle.id == JOB_ID
    assert body["payload"] == {"args": [3], "kwargs": {"b": 4}}
    assert body["timeout_seconds"] == 45
    assert body["max_retries"] == 2
    assert body["priority"] == "high"
    assert body["tags"] == ["dekorator"]
    assert body["runtime"] == "python"
    assert "def kopaytir(a: int, b: int = 2) -> int:" in body["code"]
    assert RESULT_MARKER in body["code"]


def test_apply_async_idempotency_kalitini_uzatadi(app: Durabl) -> None:
    """`apply_async` qo'shimcha sozlamalarni `submit`ga uzatadi."""

    @app.task()
    def ish(x: int) -> int:
        return x

    with respx.mock(base_url=BASE_URL) as router:
        route = router.post("/api/v1/jobs").mock(
            return_value=httpx.Response(201, json=job_payload())
        )
        ish.apply_async((5,), None, idempotency_key="idem-77", priority="low")

    request = route.calls.last.request
    assert request.headers["idempotency-key"] == "idem-77"
    assert json.loads(request.content)["priority"] == "low"


def test_call_qiymatni_qaytaradi(app: Durabl) -> None:
    """`call()` job tugashini kutadi va funksiya qiymatini qaytaradi."""

    @app.task(timeout=5, retries=0)
    def ishla(x: int) -> int:
        return x + 1

    stdout = json.dumps({RESULT_MARKER: 11}) + "\n"
    with respx.mock(base_url=BASE_URL) as router:
        router.post("/api/v1/jobs").mock(
            return_value=httpx.Response(201, json=job_payload(status="queued"))
        )
        router.get(JOB_URL).mock(
            return_value=httpx.Response(200, json=job_payload(status="success", exit_code=0))
        )
        router.get(f"{JOB_URL}/result").mock(
            return_value=httpx.Response(200, json=result_payload(stdout=stdout))
        )
        value = ishla.call(10)

    assert value == 11


def test_call_muvaffaqiyatsizlikda_xato_beradi(app: Durabl) -> None:
    """Job fail bo'lsa `call()` `JobFailedError` tashlaydi."""

    @app.task(timeout=5, retries=0)
    def buziq() -> int:
        raise RuntimeError("buzildi")

    with respx.mock(base_url=BASE_URL) as router:
        router.post("/api/v1/jobs").mock(
            return_value=httpx.Response(201, json=job_payload(status="queued"))
        )
        router.get(JOB_URL).mock(
            return_value=httpx.Response(
                200, json=job_payload(status="failed", exit_code=1, error="RuntimeError")
            )
        )
        router.get(f"{JOB_URL}/result").mock(
            return_value=httpx.Response(
                200, json=result_payload(status="failed", exit_code=1, stderr="RuntimeError\n")
            )
        )
        with pytest.raises(JobFailedError) as excinfo:
            buziq.call()

    assert excinfo.value.result is not None
    assert excinfo.value.result.exit_code == 1


# ---------------------------------------------------------------------------
# Global `durabl` obyekti
# ---------------------------------------------------------------------------


def test_durabl_configure_va_dangasa_mijoz(monkeypatch: pytest.MonkeyPatch) -> None:
    """`configure()` sozlamani saqlaydi, mijoz esa birinchi murojaatda yaratiladi."""
    instance = Durabl()
    assert instance._client is None

    config = instance.configure(api_key=API_KEY, base_url=BASE_URL, timeout=7)
    assert config.api_key == API_KEY
    assert config.timeout == 7.0
    assert instance._client is None  # hali yaratilmadi

    client = instance.client
    assert isinstance(client, DurablClient)
    assert client.config.base_url == BASE_URL
    # Takroriy murojaatda bir xil obyekt qaytadi.
    assert instance.client is client

    instance.close()
    assert instance._client is None


def test_durabl_kalitsiz_mijoz_yaratmaydi() -> None:
    """API kalit berilmasa tushunarli maslahat bilan xato chiqadi."""
    instance = Durabl()
    with pytest.raises(DurablConfigError) as excinfo:
        _ = instance.client

    assert "durabl.configure" in str(excinfo.value)


def test_durabl_global_obyekt_dekorator_bilan(client: DurablClient) -> None:
    """Global `durabl` obyekti orqali dekorator va `submit` ishlaydi."""
    from durabl import durabl as global_durabl

    global_durabl.set_client(client)
    try:

        @global_durabl.task(timeout=20)
        def salomlash(ism: str) -> str:
            return f"Salom, {ism}"

        with respx.mock(base_url=BASE_URL) as router:
            route = router.post("/api/v1/jobs").mock(
                return_value=httpx.Response(201, json=job_payload())
            )
            handle = salomlash.delay("Durabl")
            qosh = global_durabl.submit("print(1)")

        assert handle.id == JOB_ID
        assert qosh.id == JOB_ID
        assert route.call_count == 2
        assert salomlash.run("Durabl") == "Salom, Durabl"
    finally:
        # Global holatni tozalaymiz, boshqa testlarga ta'sir qilmasligi uchun.
        global_durabl._client = None
        global_durabl.reset()


def test_sozlamasiz_vazifa_global_mijozdan_foydalanadi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vazifaga mijoz berilmasa, global `durabl.client` ishlatiladi."""
    monkeypatch.setenv("DURABL_API_KEY", API_KEY)
    monkeypatch.setenv("DURABL_BASE_URL", BASE_URL)
    instance = Durabl()

    @instance.task()
    def oddiy() -> int:
        return 1

    with respx.mock(base_url=BASE_URL) as router:
        router.post("/api/v1/jobs").mock(
            return_value=httpx.Response(201, json=job_payload())
        )
        try:
            handle = oddiy.delay()
        finally:
            instance.close()

    assert handle.id == JOB_ID


# ---------------------------------------------------------------------------
# Asinxron vazifa
# ---------------------------------------------------------------------------


async def test_async_task_delay() -> None:
    """`durabl.async_task` asinxron mijoz bilan ishlaydi."""
    instance = Durabl()
    async with AsyncDurablClient(api_key=API_KEY, base_url=BASE_URL) as async_http:

        @instance.async_task(async_http, timeout=12, retries=0)
        def hisobla(a: int, b: int) -> int:
            return a + b

        with respx.mock(base_url=BASE_URL) as router:
            route = router.post("/api/v1/jobs").mock(
                return_value=httpx.Response(201, json=job_payload(status="queued"))
            )
            handle = await hisobla.delay(1, b=2)

    body = json.loads(route.calls.last.request.content)
    assert handle.id == JOB_ID
    assert body["payload"] == {"args": [1], "kwargs": {"b": 2}}
    assert body["timeout_seconds"] == 12
    assert hisobla.run(1, 2) == 3
