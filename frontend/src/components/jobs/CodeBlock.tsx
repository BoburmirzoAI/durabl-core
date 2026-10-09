'use client'

import { useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils/cn'
import { runtimeStyle } from '@/lib/utils/status'
import { StatusDot } from '@/components/common/StatusDot'
import type { Runtime } from '@/types'
import { useCopy } from '@/lib/hooks/useCopy'

/**
 * Kod bloki — dizayndagi yig'iladigan "Submitted Code" paneli.
 *
 * Sintaksis bo'yash tashqi kutubxonasiz: yengil regex tokenizatsiya.
 * Prism/Shiki 40–200KB olib keladi, bu yerda esa faqat Python va JS
 * uchun kalit so'z/matn/izoh/raqam ajratish kerak.
 */
const PY_KEYWORDS =
  /\b(def|return|import|from|class|if|elif|else|for|while|try|except|finally|with|as|in|not|and|or|is|None|True|False|lambda|yield|raise|assert|pass|break|continue|global|async|await)\b/g
const JS_KEYWORDS =
  /\b(const|let|var|function|return|if|else|for|while|try|catch|finally|class|new|typeof|instanceof|in|of|null|undefined|true|false|async|await|throw|export|import|from|module|require)\b/g

interface Token {
  text: string
  kind: 'plain' | 'comment' | 'string' | 'number' | 'keyword'
}

function tokenize(line: string, runtime: Runtime): Token[] {
  // Izoh butun qatorni egallaydi
  const commentIndex = runtime === 'python' ? line.indexOf('#') : line.indexOf('//')
  if (commentIndex === 0) return [{ text: line, kind: 'comment' }]

  const tokens: Token[] = []
  const code = commentIndex > 0 ? line.slice(0, commentIndex) : line
  const comment = commentIndex > 0 ? line.slice(commentIndex) : ''

  // Matnlar (string) birinchi ajratiladi — ular ichidagi kalit so'z bo'yalmasligi kerak
  const stringPattern = /(['"`])(?:\\.|(?!\1)[^\\])*\1/g
  let lastIndex = 0
  let match: RegExpExecArray | null

  const pushPlain = (text: string): void => {
    if (!text) return
    const keywords = runtime === 'python' ? PY_KEYWORDS : JS_KEYWORDS
    let cursor = 0
    keywords.lastIndex = 0
    let kw: RegExpExecArray | null
    while ((kw = keywords.exec(text)) !== null) {
      if (kw.index > cursor) {
        tokens.push(...splitNumbers(text.slice(cursor, kw.index)))
      }
      tokens.push({ text: kw[0], kind: 'keyword' })
      cursor = kw.index + kw[0].length
    }
    if (cursor < text.length) tokens.push(...splitNumbers(text.slice(cursor)))
  }

  while ((match = stringPattern.exec(code)) !== null) {
    pushPlain(code.slice(lastIndex, match.index))
    tokens.push({ text: match[0], kind: 'string' })
    lastIndex = match.index + match[0].length
  }
  pushPlain(code.slice(lastIndex))

  if (comment) tokens.push({ text: comment, kind: 'comment' })
  return tokens
}

function splitNumbers(text: string): Token[] {
  const tokens: Token[] = []
  const pattern = /\b\d+(?:\.\d+)?\b/g
  let cursor = 0
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) tokens.push({ text: text.slice(cursor, match.index), kind: 'plain' })
    tokens.push({ text: match[0], kind: 'number' })
    cursor = match.index + match[0].length
  }
  if (cursor < text.length) tokens.push({ text: text.slice(cursor), kind: 'plain' })
  return tokens
}

const TOKEN_CLASS: Record<Token['kind'], string> = {
  plain: 'text-fg-soft',
  comment: 'italic text-fg-faint',
  string: 'text-success',
  number: 'text-pending',
  keyword: 'font-medium text-accent-light',
}

export function CodeBlock({
  code,
  runtime,
  title = 'Submitted Code',
  collapsible = true,
  defaultOpen = false,
  maxHeight = 420,
}: {
  code: string
  runtime: Runtime
  title?: string
  collapsible?: boolean
  defaultOpen?: boolean
  maxHeight?: number
}) {
  const [open, setOpen] = useState(defaultOpen || !collapsible)
  const [copied, setCopied] = useState(false)
  const copy = useCopy()

  const lines = useMemo(() => code.replace(/\n$/, '').split('\n'), [code])
  const style = runtimeStyle(runtime)

  const onCopy = async (): Promise<void> => {
    const ok = await copy(code, 'Code copied')
    if (!ok) return
    setCopied(true)
    setTimeout(() => setCopied(false), 1_500)
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-surface">
      <div
        className={cn(
          'flex items-center gap-2.5 px-4 py-3.5',
          open && 'border-b border-line-inner',
        )}
      >
        {collapsible ? (
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
            className="flex items-center gap-2.5 text-left"
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={cn('text-fg-faint transition-transform', open && 'rotate-90')}
              aria-hidden
            >
              <path d="M9 6l6 6-6 6" />
            </svg>
            <span className="text-md font-semibold text-fg">{title}</span>
          </button>
        ) : (
          <span className="text-md font-semibold text-fg">{title}</span>
        )}

        <Badge className={cn(style.bg, style.text)}>
          <StatusDot className={style.dot} size="xs" />
          {runtime === 'python' ? 'Python 3.12' : 'Node 22'}
        </Badge>

        <Button
          variant="secondary"
          size="sm"
          onClick={() => void onCopy()}
          className="ml-auto bg-canvas"
        >
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>

      {open ? (
        <div
          // Pastda qo'shimcha bo'sh joy: oxirgi qator chetga yopishib qolsa
          // kod davom etayotgandek ko'rinadi. `pb-7` kod TUGAGANINI bildiradi.
          className="overflow-auto bg-canvas-deep pb-7 pt-2.5 font-mono text-sm leading-[1.7]"
          style={{ maxHeight }}
        >
          {lines.map((line, index) => (
            <div key={index} className="flex items-baseline px-0">
              <span className="w-[46px] shrink-0 select-none pr-3.5 text-right text-fg-ghost">
                {index + 1}
              </span>
              <span className="min-w-0 whitespace-pre-wrap break-words pr-4">
                {line.length === 0
                  ? ' '
                  : tokenize(line, runtime).map((token, i) => (
                      <span key={i} className={TOKEN_CLASS[token.kind]}>
                        {token.text}
                      </span>
                    ))}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}
