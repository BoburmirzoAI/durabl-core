#!/usr/bin/env node
'use strict';

/**
 * Durabl — Node runner'ning kirish nuqtasi (entrypoint).
 *
 * Sandbox konteyneri ichida yagona protsess sifatida ishga tushadi, mijoz
 * kodini bajaradi va natijani fayl orqali backend'ga qaytaradi.
 *
 * Backend (`app/execution/`) bilan shartnoma:
 *   - ish katalogi  : /sandbox              (constants.SANDBOX_WORKDIR)
 *   - mijoz kodi    : /sandbox/main.js      (constants.SANDBOX_CODE_FILENAME)
 *   - argumentlar   : /sandbox/payload.json (bo'lishi shart emas)
 *   - natija        : /sandbox/result.json  (constants.SANDBOX_RESULT_FILENAME)
 *   - stdout/stderr : konteyner loglari orqali real vaqtda yig'iladi
 *
 * `result.json` shakli — `result_collector` AYNAN shu kalitlarni o'qiydi:
 *   { ok, exit_code, result, error, error_type, traceback,
 *     duration_ms, stdout_bytes, stderr_bytes, truncated }
 *
 * Natija olishning uchta yo'li (shu tartibda):
 *   1. `module.exports.main` / `module.exports.handler` / `export default`
 *      funksiyasi bor VA `payload.json` berilgan bo'lsa — funksiya
 *      `fn(...args, ...)` ko'rinishida chaqiriladi (Promise ham qo'llanadi).
 *   2. Kod stdout'ga `console.log(JSON.stringify({ __durabl_result__: ... }))`
 *      chiqarsa — oxirgi shunday qator natija deb olinadi (JS SDK shu usulda).
 *   3. Aks holda natija `null`.
 *
 * `vm` moduli ATAYLAB ishlatilmaydi: u izolyatsiya bermaydi va
 * `NODE_FORBIDDEN_MODULES` ro'yxatida. Haqiqiy izolyatsiya gVisor + konteyner
 * darajasida ta'minlanadi.
 */

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

// ---------------------------------------------------------------------------
// Shartnoma konstantalari (backend `app/constants.py` bilan bir xil)
// ---------------------------------------------------------------------------

const DEFAULT_WORKDIR = '/sandbox';
const CODE_FILENAME = 'main.js';
const PAYLOAD_FILENAME = 'payload.json';
const RESULT_FILENAME = 'result.json';

/** SDK stdout orqali natija uzatishda ishlatadigan kalit. */
const RESULT_MARKER = '__durabl_result__';
/** Natija sifatida chaqiriladigan funksiya nomlari (tartib muhim). */
const ENTRY_FUNCTION_NAMES = ['main', 'handler'];

/** Yig'iladigan chiqish chegarasi (1 MB) — `settings.MAX_OUTPUT_BYTES`. */
const DEFAULT_MAX_OUTPUT_BYTES = 1048576;
/** Marker qatorini qidirishda nechta nomzod tahlil qilinadi. */
const MAX_MARKER_ATTEMPTS = 50;

const EXIT_OK = 0;
const EXIT_ERROR = 1;
const EXIT_TIMEOUT = 124;     // `timeout(1)` an'anasi
const EXIT_TERMINATED = 143;  // 128 + SIGTERM(15)

// ---------------------------------------------------------------------------
// Muhit o'zgaruvchilari
// ---------------------------------------------------------------------------

/** Muhit o'zgaruvchisidan butun son o'qiydi; xato bo'lsa — standart qiymat. */
function envInt(name, fallback) {
  const raw = (process.env[name] || '').trim();
  if (!raw) return fallback;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

/** Kod fayli nomi (backend boshqa nom bersa ham ishlaydi). */
function codeFilename() {
  return (process.env.DURABL_SANDBOX_CODE_FILENAME || '').trim() || CODE_FILENAME;
}

/**
 * Ish katalogini aniqlaydi.
 *
 * Tartib: `DURABL_SANDBOX_WORKDIR` -> `/sandbox` (kod fayli shunda bo'lsa)
 * -> joriy katalog. Oxirgi variant lokal sinovlar uchun (macOS'da `/sandbox`
 * mavjud emas).
 */
function resolveWorkdir() {
  const override = (process.env.DURABL_SANDBOX_WORKDIR || '').trim();
  if (override) return override;
  try {
    if (fs.statSync(path.join(DEFAULT_WORKDIR, codeFilename())).isFile()) {
      return DEFAULT_WORKDIR;
    }
  } catch {
    // `/sandbox` mavjud emas — joriy katalogga o'tamiz.
  }
  return process.cwd();
}

// ---------------------------------------------------------------------------
// Chiqishni ikki joyga yozuvchi "tee"
// ---------------------------------------------------------------------------

/** Matnni UTF-8 baytlari bo'yicha kesadi (yarim belgi qolmasligi uchun). */
function cutToBytes(text, limit) {
  if (limit <= 0) return '';
  return Buffer.from(text, 'utf8').subarray(0, limit).toString('utf8');
}

/**
 * Oqimning `write` metodini o'rab oladi: matn xotirada yig'iladi VA haqiqiy
 * oqimga ham uzatiladi (backend konteyner logini real vaqtda o'qiydi).
 */
function createTee(stream, limit) {
  const original = stream.write.bind(stream);
  const state = {
    chunks: [],
    captured: 0,
    total: 0,
    truncated: false,
    text() {
      return state.chunks.join('');
    },
    restore() {
      stream.write = original;
    },
  };

  stream.write = function durablTeeWrite(chunk, encoding, callback) {
    try {
      let text = '';
      if (typeof chunk === 'string') {
        text = chunk;
      } else if (chunk) {
        text = Buffer.from(chunk).toString('utf8');
      }
      const size = Buffer.byteLength(text, 'utf8');
      if (size > 0) {
        state.total += size;
        const room = limit - state.captured;
        if (room <= 0) {
          state.truncated = true;
        } else if (size <= room) {
          state.chunks.push(text);
          state.captured += size;
        } else {
          state.chunks.push(cutToBytes(text, room));
          state.captured = limit;
          state.truncated = true;
        }
      }
    } catch {
      // Ushlashdagi xato mijoz kodining chiqishini buzmasligi kerak.
    }
    return original(chunk, encoding, callback);
  };

  return state;
}

// ---------------------------------------------------------------------------
// Payload va natija
// ---------------------------------------------------------------------------

/** `payload.json` o'qilmaganda tashlanadigan xato. */
class PayloadError extends Error {
  constructor(message) {
    super(message);
    this.name = 'PayloadError';
  }
}

/**
 * `payload.json` ni o'qiydi; fayl bo'lmasa `null` qaytaradi.
 * Ichida obyekt bo'lmasa (ro'yxat, son...) — yagona argument sifatida o'raladi.
 */
function loadPayload(payloadPath) {
  let raw;
  try {
    if (!fs.statSync(payloadPath).isFile()) return null;
    raw = fs.readFileSync(payloadPath, 'utf8');
  } catch (err) {
    if (err && (err.code === 'ENOENT' || err.code === 'ENOTDIR')) return null;
    throw new PayloadError(`payload.json o'qilmadi: ${err && err.message}`);
  }
  if (!raw.trim()) return {};
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    throw new PayloadError(`payload.json yaroqli JSON emas: ${err && err.message}`);
  }
  if (parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)) {
    return parsed;
  }
  return { args: [parsed], kwargs: {} };
}

/**
 * Payload'dan argumentlar ro'yxatini yasaydi.
 *
 * JavaScript'da nomli argumentlar yo'q, shuning uchun `kwargs` (bo'sh
 * bo'lmasa) oxirgi pozitsion argument — obyekt sifatida uzatiladi. Python
 * SDK bilan bir xil `payload` shakli saqlanadi.
 */
function buildArgs(payload) {
  let args = payload.args;
  if (args === undefined || args === null) {
    args = [];
  } else if (!Array.isArray(args)) {
    args = [args];
  }
  const kwargs = payload.kwargs;
  const hasKwargs =
    kwargs !== undefined &&
    kwargs !== null &&
    typeof kwargs === 'object' &&
    !Array.isArray(kwargs) &&
    Object.keys(kwargs).length > 0;
  return hasKwargs ? [...args, kwargs] : [...args];
}

/** JSON'ga tushmaydigan qiymatlarni matnga aylantiradi (oxirgi chora). */
function jsonReplacer(_key, value) {
  if (typeof value === 'bigint') return value.toString();
  if (typeof value === 'function') return undefined;
  if (value === undefined) return undefined;
  if (value instanceof Error) {
    return { name: value.name, message: value.message, stack: value.stack };
  }
  if (value instanceof Map) return Object.fromEntries(value);
  if (value instanceof Set) return [...value];
  return value;
}

/**
 * Natijani JSON'ga tushadigan ko'rinishga keltiradi.
 * `{ value, warning }` qaytaradi; serializatsiya imkonsiz bo'lsa value = null.
 */
function normalizeResult(value) {
  if (value === undefined || value === null) return { value: null, warning: null };
  try {
    const encoded = JSON.stringify(value, jsonReplacer);
    if (encoded === undefined) return { value: null, warning: null };
    return { value: JSON.parse(encoded), warning: null };
  } catch (err) {
    return { value: null, warning: `natija JSON'ga aylantirilmadi: ${err && err.message}` };
  }
}

/**
 * stdout'dan `{"__durabl_result__": ...}` qatorini topadi (oxiridan boshlab).
 * `{ value, found }` qaytaradi.
 */
function extractMarkerResult(stdoutText) {
  if (!stdoutText || !stdoutText.includes(RESULT_MARKER)) {
    return { value: null, found: false };
  }
  const lines = stdoutText.split('\n');
  let attempts = 0;
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const line = lines[i];
    if (!line.includes(RESULT_MARKER)) continue;
    attempts += 1;
    if (attempts > MAX_MARKER_ATTEMPTS) break;
    try {
      const parsed = JSON.parse(line.trim());
      if (
        parsed !== null &&
        typeof parsed === 'object' &&
        Object.prototype.hasOwnProperty.call(parsed, RESULT_MARKER)
      ) {
        return { value: parsed[RESULT_MARKER], found: true };
      }
    } catch {
      // Bu qator JSON emas — keyingisini tekshiramiz.
    }
  }
  return { value: null, found: false };
}

/**
 * `result.json` ni atomik yozadi (vaqtinchalik fayl + `rename`), shunda
 * backend yarim yozilgan faylni o'qib qolmaydi.
 */
function writeResult(resultPath, document) {
  let raw;
  try {
    raw = JSON.stringify(document, jsonReplacer);
  } catch {
    // Hech bo'lmasa minimal natija yozilishi kerak.
    raw = JSON.stringify({
      ok: false,
      exit_code: EXIT_ERROR,
      result: null,
      error: "natija serializatsiya qilinmadi",
      error_type: 'SerializationError',
      traceback: null,
      duration_ms: document.duration_ms || 0,
      stdout_bytes: document.stdout_bytes || 0,
      stderr_bytes: document.stderr_bytes || 0,
      truncated: Boolean(document.truncated),
    });
  }
  const tmpPath = `${resultPath}.tmp`;
  try {
    fs.writeFileSync(tmpPath, raw, { encoding: 'utf8' });
    fs.renameSync(tmpPath, resultPath);
  } catch {
    // Atomik yozuv imkonsiz bo'lsa — to'g'ridan-to'g'ri yozamiz.
    fs.writeFileSync(resultPath, raw, { encoding: 'utf8' });
  }
}

// ---------------------------------------------------------------------------
// Mijoz modulini yuklash
// ---------------------------------------------------------------------------

/** Xato ESM sintaksisi sababli yuzaga kelganini aniqlaydi. */
function isEsmSyntaxError(err) {
  if (!err || !err.message) return false;
  return (
    /Cannot use import statement outside a module/.test(err.message) ||
    /Unexpected token 'export'/.test(err.message) ||
    /await is only valid/.test(err.message)
  );
}

/**
 * `/sandbox/main.js` ni yuklaydi.
 *
 * Dinamik `import()` ishlatiladi: CommonJS fayl uchun `module.exports`
 * `default` sifatida keladi, ESM fayl uchun esa eksportlar to'g'ridan-to'g'ri
 * ko'rinadi. `main.js` kengaytmasi `.js` bo'lgani uchun ESM sintaksisi
 * xatoga olib keladi — bunda fayl `.mjs` nusxasi orqali qayta yuklanadi.
 */
async function loadUserModule(codePath) {
  try {
    return await import(pathToFileURL(codePath).href);
  } catch (err) {
    if (!isEsmSyntaxError(err)) throw err;
    const candidates = [
      `${codePath}.durabl.mjs`,
      path.join(os.tmpdir(), `durabl-${process.pid}.mjs`),
    ];
    for (const candidate of candidates) {
      try {
        fs.copyFileSync(codePath, candidate);
      } catch {
        continue; // bu joy yozuvga yopiq — keyingisini sinaymiz
      }
      try {
        return await import(pathToFileURL(candidate).href);
      } finally {
        try {
          fs.unlinkSync(candidate);
        } catch {
          // Tozalash muvaffaqiyatsiz bo'lsa ham natijaga ta'sir qilmaydi.
        }
      }
    }
    throw err;
  }
}

/** Moduldan kirish funksiyasini topadi (`main`, `handler`, `export default`). */
function resolveEntryFunction(mod) {
  if (!mod) return null;
  const sources = [mod, mod.default];
  for (const source of sources) {
    if (!source) continue;
    for (const name of ENTRY_FUNCTION_NAMES) {
      if (typeof source[name] === 'function') return source[name];
    }
  }
  if (typeof mod.default === 'function') return mod.default;
  return null;
}

/**
 * Izma-izni (stack) mijoz nuqtai nazaridan tozalaydi: Node'ning ichki
 * kadrlari va entrypoint'ning o'z kadrlari olib tashlanadi — mijozga faqat
 * o'z kodidagi qatorlar ko'rinishi kerak.
 */
function cleanStack(stack) {
  if (!stack) return null;
  const lines = String(stack).split('\n');
  const kept = lines.filter((line, index) => {
    if (index === 0) return true; // xato xabari har doim qoladi
    if (!/^\s*at /.test(line)) return true;
    if (line.includes('node:internal')) return false;
    if (line.includes(__filename)) return false;
    return true;
  });
  return kept.join('\n');
}

// ---------------------------------------------------------------------------
// Asosiy oqim
// ---------------------------------------------------------------------------

async function run() {
  const startedAt = process.hrtime.bigint();

  const workdir = resolveWorkdir();
  const codePath = path.join(workdir, codeFilename());
  const payloadPath = path.join(workdir, PAYLOAD_FILENAME);
  const resultPath = path.join(
    workdir,
    (process.env.DURABL_SANDBOX_RESULT_FILENAME || '').trim() || RESULT_FILENAME,
  );

  const outputLimit = envInt('DURABL_MAX_OUTPUT_BYTES', DEFAULT_MAX_OUTPUT_BYTES);
  const timeoutSeconds = envInt('DURABL_SANDBOX_TIMEOUT_SECONDS', 0);

  const teeOut = createTee(process.stdout, outputLimit);
  const teeErr = createTee(process.stderr, outputLimit);

  // Natija bir martagina yozilishi kerak — qaysi yo'l bilan tugasa ham.
  const state = { written: false, finished: false };

  /** O'tgan vaqt (millisekund). */
  const durationMs = () => Number((process.hrtime.bigint() - startedAt) / 1000000n);

  /** Natija hujjatini yasaydi. */
  function buildDocument(outcome) {
    return {
      ok: outcome.ok,
      exit_code: outcome.exitCode,
      result: outcome.result === undefined ? null : outcome.result,
      error: outcome.error || null,
      error_type: outcome.errorType || null,
      traceback: outcome.traceback || null,
      duration_ms: durationMs(),
      stdout_bytes: teeOut.total,
      stderr_bytes: teeErr.total,
      truncated: teeOut.truncated || teeErr.truncated,
    };
  }

  /** `result.json` ni yozadi (faqat bir marta). */
  function persist(outcome) {
    if (state.written) return;
    state.written = true;
    try {
      writeResult(resultPath, buildDocument(outcome));
    } catch (err) {
      process.stderr.write(`[durabl] result.json yozilmadi: ${err && err.message}\n`);
    }
  }

  /**
   * Natijani yozib, protsessni to'xtatadi.
   *
   * `process.exitCode` oldin qo'yiladi: agar oqim o'zi bo'shab tugasa ham
   * to'g'ri kod qaytadi. Keyin stdout bo'shashini kutamiz (maksimum 200 ms) —
   * konteyner loglari yarim yo'lda uzilmasligi uchun.
   */
  function finish(outcome) {
    if (state.finished) return;
    state.finished = true;
    clearTimers();
    persist(outcome);
    process.exitCode = outcome.exitCode;
    const hardExit = () => process.exit(outcome.exitCode);
    let pending = 2;
    const tick = () => {
      pending -= 1;
      if (pending <= 0) hardExit();
    };
    try {
      process.stdout.write('', tick);
    } catch {
      tick();
    }
    try {
      process.stderr.write('', tick);
    } catch {
      tick();
    }
    setTimeout(hardExit, 200).unref();
  }

  // --- signallar va timeout ---
  let timeoutTimer = null;
  function clearTimers() {
    if (timeoutTimer !== null) {
      clearTimeout(timeoutTimer);
      timeoutTimer = null;
    }
  }

  for (const signalName of ['SIGTERM', 'SIGINT']) {
    process.on(signalName, () => {
      finish({
        ok: false,
        exitCode: EXIT_TERMINATED,
        result: null,
        error: `Bajarish tashqaridan to'xtatildi (${signalName})`,
        errorType: 'SandboxTerminated',
        traceback: null,
      });
    });
  }

  if (timeoutSeconds > 0) {
    timeoutTimer = setTimeout(() => {
      finish({
        ok: false,
        exitCode: EXIT_TIMEOUT,
        result: null,
        error: `Bajarish vaqti limiti oshdi (${timeoutSeconds}s)`,
        errorType: 'SandboxTimeout',
        traceback: null,
      });
    }, timeoutSeconds * 1000);
    timeoutTimer.unref();
  }

  // Mijoz kodi `process.exit()` chaqirsa ham natija yozilishi kerak.
  process.on('exit', (code) => {
    if (state.written) return;
    persist({
      ok: code === 0,
      exitCode: code,
      result: null,
      error: code === 0 ? null : `kod process.exit(${code}) bilan tugadi`,
      errorType: code === 0 ? null : 'ProcessExit',
      traceback: null,
    });
  });

  const failFromError = (err, errorType) => ({
    ok: false,
    exitCode: EXIT_ERROR,
    result: null,
    error: (err && err.message) || String(err),
    errorType: errorType || (err && err.name) || 'Error',
    traceback: cleanStack(err && err.stack) || String(err),
  });

  process.on('uncaughtException', (err) => finish(failFromError(err)));
  process.on('unhandledRejection', (reason) => {
    const err = reason instanceof Error ? reason : new Error(String(reason));
    finish(failFromError(err, 'UnhandledRejection'));
  });

  // --- tayyorlash ---
  let payload = null;
  try {
    if (!fs.statSync(codePath).isFile()) {
      throw new Error(`kod fayli topilmadi: ${codePath}`);
    }
    payload = loadPayload(payloadPath);
    process.chdir(workdir);
  } catch (err) {
    finish(failFromError(err, err instanceof PayloadError ? 'PayloadError' : undefined));
    return;
  }

  // --- mijoz kodi ---
  let returnedValue;
  let called = false;
  try {
    const mod = await loadUserModule(codePath);
    if (payload !== null) {
      const entry = resolveEntryFunction(mod);
      if (typeof entry === 'function') {
        called = true;
        returnedValue = await entry(...buildArgs(payload));
      }
    }
  } catch (err) {
    const error = err instanceof Error ? err : new Error(String(err));
    finish(failFromError(error));
    return;
  }

  // --- natijani aniqlash va yakunlash ---
  const settle = () => {
    let resultValue = null;
    if (called && returnedValue !== undefined && returnedValue !== null) {
      resultValue = returnedValue;
    } else {
      const marker = extractMarkerResult(teeOut.text());
      resultValue = marker.found ? marker.value : null;
    }

    const normalized = normalizeResult(resultValue);
    if (normalized.warning) {
      // Natija serializatsiya qilinmadi — bu xato emas, ogohlantirish.
      process.stderr.write(`[durabl] ogohlantirish: ${normalized.warning}\n`);
    }

    finish({
      ok: true,
      exitCode: EXIT_OK,
      result: normalized.value,
      error: null,
      errorType: null,
      traceback: null,
    });
  };

  if (called) {
    // Kirish funksiyasi chaqirilgan bo'lsa — natija tayyor, darhol tugatamiz
    // (serverless mantiq: funksiya qaytdi = job tugadi). Navbatda qolgan
    // asinxron ishlar ataylab bajarilmaydi.
    settle();
    return;
  }

  // Kirish funksiyasi yo'q: skript `node main.js` kabi tabiiy tugashi kerak.
  // `beforeExit` event loop bo'shaganda ishga tushadi — shunda kechiktirilgan
  // `setTimeout`/`Promise` chiqishlari ham natijaga kiradi.
  process.once('beforeExit', settle);
}

// Top-level `await` CommonJS'da ishlamaydi — async IIFE ishlatamiz.
void (async () => {
  try {
    await run();
  } catch (err) {
    // Bu yerga tushish kutilmaydi, lekin protsess jim o'lmasligi kerak.
    process.stderr.write(`[durabl] entrypoint xatosi: ${(err && err.stack) || err}\n`);
    process.exit(EXIT_ERROR);
  }
})();
