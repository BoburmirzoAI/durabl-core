'use client'

import { CodeBlock } from '@/components/jobs/CodeBlock'
import { DetailDrawer, DrawerRow, DrawerSection } from '@/components/common/DetailDrawer'
import { JsonViewer } from '@/components/common/JsonViewer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatNumber } from '@/lib/utils/format'
import { formatDate } from '@/lib/utils/time'
import type { JobTemplate } from '@/types'

/**
 * Shablonni to'liq ko'rish.
 *
 * Kod BUTUNLIGICHA ko'rsatiladi — kartadagi 6 qator shablonni tanlashga
 * yetadi, lekin ishlatishdan oldin hammasini o'qish kerak: shablon
 * sizning hisobingizda ishga tushadi va sizning kvotangizni sarflaydi.
 */
export function TemplatePreviewDrawer({
  template,
  onOpenChange,
  onUse,
}: {
  template: JobTemplate | null
  onOpenChange: (open: boolean) => void
  onUse: (template: JobTemplate) => void
}) {
  let payload: unknown = null
  let payloadError: string | null = null
  if (template) {
    try {
      payload = JSON.parse(template.payload)
    } catch (error) {
      payloadError = error instanceof Error ? error.message : 'Invalid JSON'
    }
  }

  return (
    <DetailDrawer
      open={template !== null}
      onOpenChange={onOpenChange}
      width="lg"
      title={
        <span className="flex min-w-0 items-center gap-2.5">
          <span className="truncate">{template?.name}</span>
          {template?.is_builtin ? <Badge variant="outline">Built-in</Badge> : null}
        </span>
      }
      description={template?.description}
      stats={
        template
          ? [
              { label: 'Runtime', value: template.runtime },
              { label: 'Timeout', value: `${template.timeout_seconds}s` },
              { label: 'Memory', value: `${template.memory_mb} MB` },
              { label: 'Used', value: formatNumber(template.use_count) },
            ]
          : undefined
      }
      footer={
        template ? (
          <div className="flex w-full items-center gap-2">
            <span className="min-w-0 flex-1 text-xs text-fg-faint">
              Added {formatDate(template.created_at)}
            </span>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Close
            </Button>
            <Button variant="primary" onClick={() => onUse(template)}>
              Use this template
            </Button>
          </div>
        ) : null
      }
    >
      {template ? (
        <div className="space-y-3.5">
          <DrawerSection title="Code">
            <CodeBlock code={template.code} runtime={template.runtime} title="Template code" defaultOpen />
          </DrawerSection>

          <DrawerSection title="Example payload">
            {payloadError ? (
              <p className="text-sm text-failed-text">
                This template&apos;s example payload is not valid JSON: {payloadError}
              </p>
            ) : (
              <JsonViewer data={payload} />
            )}
          </DrawerSection>

          <DrawerSection title="Defaults applied">
            <DrawerRow label="Runtime" value={template.runtime} />
            <DrawerRow label="Timeout" value={`${template.timeout_seconds} seconds`} />
            <DrawerRow label="Memory" value={`${template.memory_mb} MB`} />
            <DrawerRow label="Max retries" value={String(template.max_retries)} />
            <DrawerRow label="Priority" value={template.priority} />
            <DrawerRow label="Category" value={template.category} />
          </DrawerSection>
        </div>
      ) : null}
    </DetailDrawer>
  )
}
