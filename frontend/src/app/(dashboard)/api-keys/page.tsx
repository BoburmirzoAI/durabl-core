'use client'

import { useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useState } from 'react'

import { ErrorState } from '@/components/common/ErrorState'
import { SectionHeader } from '@/components/common/SectionHeader'
import { ApiKeysTable } from '@/components/api-keys/ApiKeysTable'
import { CreateKeyModal } from '@/components/api-keys/CreateKeyModal'
import { KeyDetailDrawer } from '@/components/api-keys/KeyDetailDrawer'
import { RotateKeyModal } from '@/components/api-keys/RotateKeyModal'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { useApiKeys } from '@/lib/hooks/useApiKeys'
import type { ApiKey } from '@/types'

/** API kalitlar — dizayndagi jadval + yaratish dialogi. */
export default function ApiKeysPage() {
  return (
    <Suspense fallback={null}>
      <ApiKeysContent />
    </Suspense>
  )
}

function ApiKeysContent() {
  const searchParams = useSearchParams()
  const [modalOpen, setModalOpen] = useState(false)
  const [detailKey, setDetailKey] = useState<ApiKey | null>(null)
  const [rotateKey, setRotateKey] = useState<ApiKey | null>(null)
  const keys = useApiKeys()

  // Tafsilot paneli jadvaldagi NUSXAni ushlab qolmasligi kerak: huquq
  // o'zgargach ro'yxat yangilanadi, panel esa eski ma'lumotni ko'rsatishi
  // mumkin edi. Shuning uchun faqat `id` saqlanadi va joriy qator qayta
  // topiladi.
  const detail = detailKey ? (keys.data?.find((k) => k.id === detailKey.id) ?? detailKey) : null

  useEffect(() => {
    if (searchParams.get('new') === '1') setModalOpen(true)
  }, [searchParams])

  return (
    <>
      <SectionHeader
        title="API Keys"
        description="Authenticate SDK and HTTP requests with the X-API-Key header"
        actions={
          <Button variant="primary" size="md" onClick={() => setModalOpen(true)}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden>
              <path d="M12 5v14M5 12h14" />
            </svg>
            Create key
          </Button>
        }
      />

      {keys.error ? (
        <ErrorState error={keys.error} onRetry={() => void keys.refetch()} />
      ) : (
        <ApiKeysTable
          keys={keys.data}
          loading={keys.isLoading}
          onCreate={() => setModalOpen(true)}
          onOpenDetail={setDetailKey}
          onRotate={setRotateKey}
        />
      )}

      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle className="text-md">Using your key</CardTitle>
        </CardHeader>
        <div className="grid gap-4 p-4 lg:grid-cols-2">
          <Snippet
            label="cURL"
            code={`curl -X POST https://api.durabl.dev/api/v1/jobs \\
  -H "X-API-Key: durabl_xxx" \\
  -H "Idempotency-Key: order-12345" \\
  -H "Content-Type: application/json" \\
  -d '{"code":"print(1)","runtime":"python"}'`}
          />
          <Snippet
            label="Python SDK"
            code={`from durabl import DurablClient

client = DurablClient(api_key="durabl_xxx")

job = client.submit(
    code="print('hello')",
    runtime="python",
    idempotency_key="order-12345",
)
result = client.wait_for_result(job.id, timeout=60)
print(result.stdout)`}
          />
        </div>
      </Card>

      <CreateKeyModal open={modalOpen} onOpenChange={setModalOpen} />

      <KeyDetailDrawer
        apiKey={detail}
        onOpenChange={(open) => {
          if (!open) setDetailKey(null)
        }}
        onRotate={setRotateKey}
      />

      <RotateKeyModal
        apiKey={rotateKey}
        onOpenChange={(open) => {
          if (!open) setRotateKey(null)
        }}
      />
    </>
  )
}

function Snippet({ label, code }: { label: string; code: string }) {
  return (
    <div>
      <div className="mb-1.5 text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
        {label}
      </div>
      <pre className="m-0 overflow-x-auto whitespace-pre rounded-lg border border-line-inner bg-canvas-deep px-3.5 py-3 font-mono text-xs leading-[1.7] text-fg-muted">
        {code}
      </pre>
    </div>
  )
}
