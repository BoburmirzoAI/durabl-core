'use client'

import { useMemo, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { useUpdateApiKeyScopes } from '@/lib/hooks/useApiKeys'
import { cn } from '@/lib/utils/cn'
import { API_KEY_SCOPES, API_KEY_SCOPE_INFO, type ApiKey, type ApiKeyScope } from '@/types'

/**
 * Kalit huquqlari muharriri.
 *
 * ## Nega checkbox ro'yxati, nima uchun izoh bilan
 *
 * `dlq:write` nomi o'zi hech narsa aytmaydi. Kalit huquqini tanlayotgan
 * odam "bu kalit nimani BUZISHI mumkin" degan savolga javob olishi kerak,
 * aks holda hamma joyga `admin` qo'yib yuboradi.
 *
 * ## Saqlash qoidasi
 *
 * O'zgarish DARHOL saqlanmaydi: huquqni olib tashlash ishlab turgan
 * integratsiyani uzadi, shuning uchun "Save" bosilishi shart. `dirty`
 * holatida panel pastida nima o'zgarayotgani aniq yoziladi.
 */
export function ScopeEditor({ apiKey }: { apiKey: ApiKey }) {
  const update = useUpdateApiKeyScopes()
  const [draft, setDraft] = useState<ApiKeyScope[]>(apiKey.scopes)

  const locked = Boolean(apiKey.revoked_at)

  const { added, removed, dirty } = useMemo(() => {
    const addedScopes = draft.filter((s) => !apiKey.scopes.includes(s))
    const removedScopes = apiKey.scopes.filter((s) => !draft.includes(s))
    return {
      added: addedScopes,
      removed: removedScopes,
      dirty: addedScopes.length > 0 || removedScopes.length > 0,
    }
  }, [draft, apiKey.scopes])

  function toggle(scope: ApiKeyScope) {
    setDraft((current) =>
      current.includes(scope) ? current.filter((s) => s !== scope) : [...current, scope],
    )
  }

  return (
    <div>
      <div className="space-y-px">
        {API_KEY_SCOPES.map((scope) => {
          const info = API_KEY_SCOPE_INFO[scope]
          const checked = draft.includes(scope)
          return (
            <label
              key={scope}
              className={cn(
                'flex cursor-pointer items-start gap-3 rounded-lg px-2.5 py-2.5 transition-colors',
                checked ? 'bg-accent/[0.06]' : 'hover:bg-surface-3',
                locked && 'cursor-not-allowed opacity-50',
              )}
            >
              <span className="mt-0.5">
                <Checkbox
                  checked={checked}
                  disabled={locked}
                  onToggle={() => toggle(scope)}
                  aria-label={info.title}
                />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-base font-medium text-fg-soft">{info.title}</span>
                  <code className="rounded bg-canvas-deep px-1.5 py-px font-mono text-2xs text-fg-faint">
                    {scope}
                  </code>
                  {info.dangerous ? <Badge variant="danger" size="sm">Dangerous</Badge> : null}
                </span>
                <span className="mt-0.5 block text-sm leading-[1.5] text-fg-dim">
                  {info.description}
                </span>
              </span>
            </label>
          )
        })}
      </div>

      {locked ? (
        <p className="mt-3 text-sm text-fg-faint">
          This key is revoked. Permissions can no longer be changed.
        </p>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-line-subtle pt-3">
          <div className="min-w-0 flex-1 text-sm text-fg-dim">
            {draft.length === 0 ? (
              <span className="text-failed-text">A key needs at least one permission.</span>
            ) : dirty ? (
              <>
                {removed.length > 0 ? (
                  <span className="text-failed-text">
                    Removing {removed.join(', ')} — clients using it start getting 403.
                  </span>
                ) : null}
                {removed.length > 0 && added.length > 0 ? ' ' : null}
                {added.length > 0 ? (
                  <span className="text-pending">Granting {added.join(', ')}.</span>
                ) : null}
              </>
            ) : (
              <span>
                {apiKey.scopes.length} permission{apiKey.scopes.length === 1 ? '' : 's'} granted.
              </span>
            )}
          </div>

          {dirty ? (
            <Button variant="ghost" size="sm" onClick={() => setDraft(apiKey.scopes)}>
              Reset
            </Button>
          ) : null}
          <Button
            variant="primary"
            size="sm"
            disabled={!dirty || draft.length === 0 || update.isPending}
            onClick={() => update.mutate({ id: apiKey.id, scopes: draft })}
          >
            {update.isPending ? 'Saving…' : 'Save permissions'}
          </Button>
        </div>
      )}
    </div>
  )
}
