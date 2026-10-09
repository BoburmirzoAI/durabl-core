'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { RelativeTime } from '@/components/common/RelativeTime'
import { cn } from '@/lib/utils/cn'
import { runtimeStyle } from '@/lib/utils/status'
import type { JobTemplate } from '@/types'

/**
 * Shablon kartasi.
 *
 * Kodning birinchi qatorlari ko'rsatiladi: shablon nomi ("CSV report
 * builder") nima qilishini aytadi, lekin QANDAY qilishini faqat kod
 * ko'rsatadi — va aynan shu nusxalashdan oldin bilish kerak bo'lgan narsa.
 */
export function TemplateCard({
  template,
  onUse,
  onPreview,
  onDelete,
}: {
  template: JobTemplate
  onUse: (template: JobTemplate) => void
  onPreview: (template: JobTemplate) => void
  onDelete: (template: JobTemplate) => void
}) {
  const runtime = runtimeStyle(template.runtime)
  const preview = template.code.split('\n').slice(0, 6).join('\n')

  return (
    <Card className="flex flex-col overflow-hidden">
      <div className="flex items-start gap-3 p-4 pb-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-md font-semibold text-fg">{template.name}</span>
            {template.is_builtin ? (
              <Badge size="sm" variant="outline">
                Built-in
              </Badge>
            ) : null}
          </div>
          <p className="mt-1 text-sm leading-[1.5] text-fg-dim">{template.description}</p>
        </div>
        <span className={cn('shrink-0 rounded-md px-2 py-0.5 text-2xs font-medium', runtime.bg, runtime.text)}>
          {template.runtime}
        </span>
      </div>

      <button
        type="button"
        onClick={() => onPreview(template)}
        aria-label={`Preview ${template.name}`}
        className="mx-4 overflow-hidden rounded-lg border border-line-inner bg-canvas-deep text-left transition-colors hover:border-line-hover"
      >
        <pre className="m-0 max-h-[108px] overflow-hidden whitespace-pre px-3 py-2.5 font-mono text-2xs leading-[1.6] text-fg-faint">
          {preview}
        </pre>
      </button>

      <div className="mt-auto flex flex-wrap items-center gap-2 p-4 pt-3">
        <span className="min-w-0 flex-1 text-xs text-fg-faint">
          <span className="rounded bg-surface-3 px-1.5 py-px">{template.category}</span>
          <span className="ml-2">
            used {template.use_count}×
            {template.last_used_at ? (
              <>
                {' · '}
                <RelativeTime value={template.last_used_at} className="inline" />
              </>
            ) : null}
          </span>
        </span>
        {!template.is_builtin ? (
          <Button variant="ghost" size="sm" onClick={() => onDelete(template)}>
            Delete
          </Button>
        ) : null}
        <Button variant="secondary" size="sm" onClick={() => onPreview(template)}>
          Preview
        </Button>
        <Button variant="primary" size="sm" onClick={() => onUse(template)}>
          Use template
        </Button>
      </div>
    </Card>
  )
}
