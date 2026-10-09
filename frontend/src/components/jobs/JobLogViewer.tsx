'use client'

import { useEffect, useMemo, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { SearchField } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Tabs } from '@/components/ui/tabs'
import { cn } from '@/lib/utils/cn'
import { formatLogTime } from '@/lib/utils/time'
import { useUiStore } from '@/stores/uiStore'
import type { JobLog, LogStream } from '@/types'
import { ICON_COPY } from '@/lib/constants/icons'
import { useCopy } from '@/lib/hooks/useCopy'
import { useSearchFocus } from '@/lib/hooks/useKeyboard'

/**
 * Terminal uslubidagi log ko'rsatuvchi — dizayndagi asosiy komponent.
 *
 * Dizayndan olingan: `#09090A` fon, mono 12px, 1.7 qator balandligi,
 * chap tomonda 46px qator raqami (`#3F3F46`), keyin vaqt, keyin 54px
 * oqim yorlig'i, keyin matn.
 *
 * Qo'shimcha (dizaynda yo'q): oqim bo'yicha filtr, matn qidiruv va
 * topilgan joyni ajratish, avtomatik siljish mantig'i, yuklab olish.
 */
const STREAM_TABS = [
  { value: 'all' as const, label: 'All' },
  { value: 'stdout' as const, label: 'stdout' },
  { value: 'stderr' as const, label: 'stderr' },
] as const

type StreamFilter = (typeof STREAM_TABS)[number]['value']

/** Oqim yorlig'i rangi. */
const STREAM_STYLES: Record<LogStream, { label: string; className: string; text: string }> = {
  stdout: { label: 'stdout', className: 'text-fg-faint', text: 'text-fg-soft' },
  stderr: { label: 'stderr', className: 'text-failed', text: 'text-failed-text' },
  system: { label: 'durabl', className: 'text-accent-light', text: 'text-fg-dim' },
}

/** 5000 qatordan oshsa faqat oxirgisi ko'rsatiladi (brauzer sekinlashmasligi uchun). */
const MAX_RENDERED = 5_000

export function JobLogViewer({
  logs,
  loading = false,
  isLive = false,
}: {
  logs: JobLog[] | undefined
  loading?: boolean
  isLive?: boolean
}) {
  const showTimestamps = useUiStore((s) => s.preferences.show_log_timestamps)
  const [stream, setStream] = useState<StreamFilter>('all')
  const [query, setQuery] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const [showAll, setShowAll] = useState(false)
  const [wrap, setWrap] = useState(true)
  //: Keyingi xatoga sakrash uchun joriy o'rin (-1 = hali boshlanmagan)
  const [errorCursor, setErrorCursor] = useState(-1)

  const scrollRef = useRef<HTMLDivElement>(null)

  const filtered = useMemo(() => {
    const rows = logs ?? []
    const q = query.trim().toLowerCase()
    return rows.filter((log) => {
      if (stream !== 'all' && log.stream !== stream) {
        // `system` yozuvlari stderr filtrida ham ko'rinadi (ular xato kontekstini beradi)
        if (!(stream === 'stderr' && log.stream === 'system')) return false
      }
      if (q && !log.content.toLowerCase().includes(q)) return false
      return true
    })
  }, [logs, stream, query])

  const truncated = !showAll && filtered.length > MAX_RENDERED
  const visible = truncated ? filtered.slice(-MAX_RENDERED) : filtered

  // Avtomatik siljish — foydalanuvchi yuqoriga surganda to'xtaydi
  useEffect(() => {
    if (!autoScroll) return
    const node = scrollRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [visible.length, autoScroll])

  const onScroll = (): void => {
    const node = scrollRef.current
    if (!node) return
    const atBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 24
    // Pastda bo'lsa avtomatik siljishni yoqamiz, yuqorida bo'lsa o'chiramiz
    if (atBottom !== autoScroll) setAutoScroll(atBottom)
  }

  const copy = useCopy()
  const searchRef = useSearchFocus()

  //: `stderr` qatorlarining ko'rinadigan ro'yxatdagi indekslari
  const errorIndexes = useMemo(
    () => visible.map((l, i) => (l.stream === 'stderr' ? i : -1)).filter((i) => i >= 0),
    [visible],
  )

  /** Keyingi `stderr` qatoriga siljiydi (aylanma). */
  const jumpToError = (): void => {
    if (errorIndexes.length === 0) return
    const next = (errorCursor + 1) % errorIndexes.length
    setErrorCursor(next)
    setAutoScroll(false)
    const target = errorIndexes[next]
    if (target === undefined) return
    scrollRef.current
      ?.querySelector(`[data-log-index="${target}"]`)
      ?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }

  const copyLogs = async (): Promise<void> => {
    await copy(visible.map((l) => l.content).join('\n'), `${visible.length} log lines copied`)
  }

  const downloadLogs = (): void => {
    const blob = new Blob([visible.map((l) => `${l.timestamp} [${l.stream}] ${l.content}`).join('\n')], {
      type: 'text/plain',
    })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${logs?.[0]?.job_id ?? 'job'}.log`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div>
      {/* Boshqaruv paneli */}
      <div className="flex flex-wrap items-center gap-2.5 border-b border-line-inner px-3.5 py-[11px]">
        <SearchField
          ref={searchRef}
          shortcut="/"
          placeholder="Filter logs…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          containerClassName="w-[240px] max-w-full bg-canvas"
          aria-label="Filter log lines"
        />

        <Tabs aria-label="Log stream" items={STREAM_TABS} value={stream} onChange={setStream} />

        <label className="flex cursor-pointer select-none items-center gap-[7px] text-sm text-fg-muted">
          <Switch
            checked={autoScroll}
            onCheckedChange={setAutoScroll}
            aria-label="Auto-scroll logs"
          />
          Auto-scroll
        </label>

        {isLive ? (
          <span className="flex items-center gap-1.5 text-xs text-success">
            <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-success" style={{ ['--pulse-color' as string]: 'var(--success)' }} />
            live
          </span>
        ) : null}

        <div className="ml-auto flex items-center gap-[7px]">
          <Button variant="secondary" size="sm" onClick={downloadLogs} className="bg-canvas">
            <Icon path="M12 3v12M7 10l5 5 5-5M4 19h16" />
            Download
          </Button>
          <Button variant="secondary" size="sm" onClick={() => void copyLogs()} className="bg-canvas">
            <Icon path={ICON_COPY} />
            Copy
          </Button>

          <Button
            variant="secondary"
            size="sm"
            onClick={jumpToError}
            disabled={errorIndexes.length === 0}
            className="bg-canvas"
            title={
              errorIndexes.length === 0
                ? 'No error lines'
                : `Jump to next error (${errorIndexes.length} total)`
            }
          >
            <Icon path="M12 3 2 20h20zM12 10v4M12 17h.01" />
            Errors
            {errorIndexes.length > 0 ? (
              <span className="ml-1 rounded-sm bg-failed/[0.16] px-1 font-mono text-2xs text-failed">
                {errorIndexes.length}
              </span>
            ) : null}
          </Button>

          <button
            type="button"
            onClick={() => setWrap((w) => !w)}
            className={cn(
              'rounded-md px-2 py-1 text-xs transition-colors',
              wrap ? 'text-fg-dim hover:text-fg' : 'bg-surface-3 text-fg',
            )}
            title={wrap ? "Qatorlar o'ralgan — bosib o'chiring" : 'Qatorlar bir chiziqda'}
          >
            {wrap ? 'wrap' : 'no wrap'}
          </button>
        </div>
      </div>

      {/* Loglar */}
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className={cn(
          'max-h-[360px] overflow-auto bg-canvas-deep py-2.5 font-mono text-sm leading-[1.7]',
          !wrap && 'overflow-x-auto',
        )}
      >
        {truncated ? (
          <button
            type="button"
            onClick={() => setShowAll(true)}
            className="mx-4 mb-2 block rounded-md border border-line bg-surface px-3 py-1.5 text-xs text-fg-muted transition-colors hover:border-line-hover hover:text-fg"
          >
            Showing last {MAX_RENDERED.toLocaleString('en-US')} of{' '}
            {filtered.length.toLocaleString('en-US')} lines — load all
          </button>
        ) : null}

        {loading && !logs ? (
          <div className="px-4 py-8 text-center text-fg-faint">Loading logs…</div>
        ) : visible.length === 0 ? (
          <div className="px-4 py-8 text-center text-fg-faint">
            {query || stream !== 'all'
              ? 'No log lines match the filter.'
              : 'No output captured for this job.'}
          </div>
        ) : (
          visible.map((log, index) => {
            const style = STREAM_STYLES[log.stream]
            return (
              <div
                key={log.id}
                data-log-index={index}
                className={cn(
                  'flex items-baseline px-0 py-px transition-colors hover:bg-surface/60',
                  // Sakrash bilan topilgan qator qisqa vaqt ajralib turadi
                  errorIndexes[errorCursor] === index && 'bg-failed/[0.10]',
                )}
              >
                <span className="w-[46px] shrink-0 select-none pr-3.5 text-right text-fg-ghost">
                  {truncated ? filtered.length - visible.length + index + 1 : index + 1}
                </span>
                {showTimestamps ? (
                  <span className="mr-3 shrink-0 text-fg-faint">{formatLogTime(log.timestamp)}</span>
                ) : null}
                <span className={cn('mr-3 w-[54px] shrink-0 text-2xs font-semibold', style.className)}>
                  {style.label}
                </span>
                <span
                  className={cn(
                    'min-w-0 pr-4',
                    wrap ? 'whitespace-pre-wrap break-words' : 'whitespace-pre',
                    style.text,
                  )}
                >
                  {query ? <Highlight text={log.content} query={query} /> : log.content}
                </span>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

/** Qidiruv natijasini ajratib ko'rsatadi. */
function Highlight({ text, query }: { text: string; query: string }) {
  const index = text.toLowerCase().indexOf(query.toLowerCase())
  if (index < 0) return <>{text}</>
  return (
    <>
      {text.slice(0, index)}
      <mark className="rounded-sm bg-accent/30 text-fg">{text.slice(index, index + query.length)}</mark>
      {text.slice(index + query.length)}
    </>
  )
}

function Icon({ path }: { path: string }) {
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d={path} />
    </svg>
  )
}
