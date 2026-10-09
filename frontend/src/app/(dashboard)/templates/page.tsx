'use client'

import { useRouter } from 'next/navigation'
import { useMemo, useState } from 'react'

import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { EmptyState } from '@/components/common/EmptyState'
import { ErrorState } from '@/components/common/ErrorState'
import { SectionHeader } from '@/components/common/SectionHeader'
import { TemplateCard } from '@/components/templates/TemplateCard'
import { TemplatePreviewDrawer } from '@/components/templates/TemplatePreviewDrawer'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { SearchField } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs } from '@/components/ui/tabs'
import { useDeleteTemplate, useMarkTemplateUsed, useTemplates } from '@/lib/hooks/useSchedules'
import { useSearchFocus } from '@/lib/hooks/useKeyboard'
import type { JobTemplate } from '@/types'

/**
 * Shablonlar — qayta ishlatiladigan job tanalari.
 *
 * ═══════════════════════════════════════════════════════════════════
 * NEGA BU SAHIFA KERAK
 * ═══════════════════════════════════════════════════════════════════
 *
 * Bir xil kod har safar qo'lda yoziladi yoki eski job'dan nusxalanadi.
 * Ikkalasi ham xatoga olib keladi: eski job'da allaqachon tuzatilgan
 * bug qaytib keladi, yoki timeout noto'g'ri qo'yiladi.
 *
 * Shablon — kod bilan BIRGA sozlamalarni (timeout, xotira, urinishlar)
 * saqlaydi, shuning uchun "ishlagan narsa"ni aynan takrorlash mumkin.
 *
 * Tayyor shablonlar (`is_builtin`) tahrirlanmaydi — ular nusxalanadi.
 */
export default function TemplatesPage() {
  const router = useRouter()
  const templates = useTemplates()
  const remove = useDeleteTemplate()
  const markUsed = useMarkTemplateUsed()
  const searchRef = useSearchFocus()

  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('all')
  const [preview, setPreview] = useState<JobTemplate | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<JobTemplate | null>(null)

  const categories = useMemo(() => {
    const unique = [...new Set((templates.data ?? []).map((t) => t.category))].sort()
    return [{ value: 'all', label: 'All' }, ...unique.map((c) => ({ value: c, label: c }))]
  }, [templates.data])

  const rows = useMemo(() => {
    const term = search.trim().toLowerCase()
    return (templates.data ?? [])
      .filter((t) => category === 'all' || t.category === category)
      .filter(
        (t) =>
          term === '' ||
          t.name.toLowerCase().includes(term) ||
          t.description.toLowerCase().includes(term) ||
          t.code.toLowerCase().includes(term),
      )
      // Oldin o'z shablonlari, keyin tayyorlari; ichida eng ko'p ishlatilgani
      .sort((a, b) => {
        if (a.is_builtin !== b.is_builtin) return a.is_builtin ? 1 : -1
        return b.use_count - a.use_count
      })
  }, [templates.data, search, category])

  /** Shablondan job yaratish sahifasiga o'tadi. */
  function openInNewJob(template: JobTemplate): void {
    markUsed.mutate(template.id)
    router.push(`/jobs/new?template=${encodeURIComponent(template.id)}`)
  }

  return (
    <>
      <SectionHeader
        title="Templates"
        description="Reusable job bodies with their settings"
        actions={
          <Button variant="primary" size="md" onClick={() => router.push('/jobs/new')}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden>
              <path d="M12 5v14M5 12h14" />
            </svg>
            New job
          </Button>
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <Tabs
          aria-label="Template category"
          items={categories}
          value={category}
          onChange={setCategory}
        />
        <SearchField
          ref={searchRef}
          shortcut="/"
          placeholder="Search name, description, code…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          containerClassName="w-[300px]"
          aria-label="Search templates"
        />
      </div>

      {templates.error ? (
        <ErrorState error={templates.error} onRetry={() => void templates.refetch()} />
      ) : templates.isLoading && !templates.data ? (
        <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {Array.from({ length: 4 }, (_, i) => (
            <Card key={i} className="p-4">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="mt-2 h-3 w-full" />
              <Skeleton className="mt-4 h-[108px] w-full" />
            </Card>
          ))}
        </div>
      ) : rows.length === 0 ? (
        <Card className="p-0">
          <EmptyState
            icon="M4 5h16v4H4zM4 12h7v7H4zM13 12h7v7h-7z"
            title="No templates match"
            description="Clear the filters, or save a job as a template from the new-job page."
          />
        </Card>
      ) : (
        <div className="grid items-stretch gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {rows.map((template) => (
            <TemplateCard
              key={template.id}
              template={template}
              onUse={openInNewJob}
              onPreview={setPreview}
              onDelete={setConfirmDelete}
            />
          ))}
        </div>
      )}

      <TemplatePreviewDrawer
        template={preview}
        onOpenChange={(open) => {
          if (!open) setPreview(null)
        }}
        onUse={(template) => {
          setPreview(null)
          openInNewJob(template)
        }}
      />

      <ConfirmDialog
        open={confirmDelete !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmDelete(null)
        }}
        title="Delete template?"
        description={
          confirmDelete
            ? `"${confirmDelete.name}" is removed. Jobs already created from it are unaffected.`
            : ''
        }
        confirmLabel="Delete template"
        destructive
        pending={remove.isPending}
        onConfirm={() => {
          if (confirmDelete) remove.mutate(confirmDelete.id)
          setConfirmDelete(null)
        }}
      />
    </>
  )
}
