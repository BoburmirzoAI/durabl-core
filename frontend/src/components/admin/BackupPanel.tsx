'use client'

import { useState } from 'react'

import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { SkeletonRows } from '@/components/ui/skeleton'
import { RelativeTime } from '@/components/common/RelativeTime'
import { CronBuilder } from '@/components/schedules/CronBuilder'
import {
  useBackupSettings,
  useBackups,
  useRestoreBackup,
  useTriggerBackup,
  useUpdateBackupSettings,
} from '@/lib/hooks/usePlatform'
import { formatBytes } from '@/lib/utils/format'
import { diffMs, formatTimestamp } from '@/lib/utils/time'
import type { BackupRecord } from '@/types'

const GRID = 'minmax(140px,1fr) 104px 94px 94px 110px 92px'

const STATUS_CLASS: Record<BackupRecord['status'], string> = {
  completed: 'bg-success/[0.12] text-success',
  running: 'bg-running/[0.12] text-running',
  failed: 'bg-failed/[0.12] text-failed',
}

/**
 * Zaxira nusxalar.
 *
 * ## Nega tiklash tugmasi shunchalik "qo'rqinchli"
 *
 * Tiklash — bu bazani ALMASHTIRISH. Oxirgi nusxadan keyingi barcha
 * ma'lumot yo'qoladi va xizmat bir necha daqiqa to'xtaydi. Bu tugma
 * boshqa tugmalarga o'xshamasligi kerak.
 *
 * Mock rejimida hech narsa tiklanmaydi va buni tasdiq oynasi ochiq
 * aytadi — soxta "tiklandi" xabari eng zararli yolg'on bo'lardi.
 */
export function BackupPanel() {
  const backups = useBackups()
  const settings = useBackupSettings()
  const updateSettings = useUpdateBackupSettings()
  const trigger = useTriggerBackup()
  const restore = useRestoreBackup()
  const [confirmRestore, setConfirmRestore] = useState<BackupRecord | null>(null)

  return (
    <>
      <Card className="overflow-hidden">
        <CardHeader>
          <div className="flex flex-wrap items-start gap-4">
            <div>
              <CardTitle className="text-md">Backups</CardTitle>
              <CardDescription>
                {settings.data?.last_successful_at ? (
                  <>
                    Last successful backup <RelativeTime value={settings.data.last_successful_at} />{' '}
                    to <span className="font-mono">{settings.data.destination}</span>
                  </>
                ) : (
                  'No successful backup recorded yet'
                )}
              </CardDescription>
            </div>
            <Button
              variant="primary"
              className="ml-auto"
              disabled={trigger.isPending}
              onClick={() => trigger.mutate()}
            >
              {trigger.isPending ? 'Starting…' : 'Back up now'}
            </Button>
          </div>
        </CardHeader>

        {settings.data ? (
          <div className="space-y-3.5 border-b border-line-inner p-4">
            <div className="flex items-start justify-between gap-6">
              <div className="min-w-0">
                <div className="text-base text-fg-soft">Scheduled backups</div>
                <div className="mt-0.5 text-sm leading-[1.5] text-fg-faint">
                  Kept for {settings.data.retention_days} days, then deleted from the destination.
                </div>
              </div>
              <Switch
                checked={settings.data.enabled}
                onCheckedChange={(enabled) => updateSettings.mutate({ enabled })}
                aria-label="Scheduled backups"
              />
            </div>

            {settings.data.enabled ? (
              <CronBuilder
                label="Backup schedule"
                value={settings.data.cron}
                onChange={(cron) => updateSettings.mutate({ cron })}
              />
            ) : (
              <div className="rounded-lg border border-pending/25 bg-pending/[0.07] px-3.5 py-2.5 text-sm text-pending">
                Automatic backups are off. The only copies are the ones below.
              </div>
            )}
          </div>
        ) : null}

        <div className="overflow-x-auto">
          <div className="min-w-[700px]">
            <div className="table-head grid items-center gap-3 px-4" style={{ gridTemplateColumns: GRID }}>
              <span>Started</span>
              <span>Status</span>
              <span className="text-right">Size</span>
              <span className="text-right">Duration</span>
              <span>Trigger</span>
              <span className="sr-only">Actions</span>
            </div>

            {backups.isLoading && !backups.data ? (
              <SkeletonRows rows={5} columns={GRID} />
            ) : (
              (backups.data ?? []).map((backup) => {
                const duration = diffMs(backup.started_at, backup.finished_at)
                return (
                  <div
                    key={backup.id}
                    className="grid min-h-[48px] items-center gap-3 border-b border-line-subtle px-4 py-2 last:border-b-0 hover:bg-surface-3"
                    style={{ gridTemplateColumns: GRID }}
                  >
                    <span className="min-w-0">
                      <span className="tabular block truncate font-mono text-xs text-fg-muted">
                        {formatTimestamp(backup.started_at).replace(' UTC', '')}
                      </span>
                      {backup.error ? (
                        <span className="block truncate text-2xs text-failed-text" title={backup.error}>
                          {backup.error}
                        </span>
                      ) : null}
                    </span>
                    <span>
                      <Badge size="sm" className={STATUS_CLASS[backup.status]}>
                        {backup.status}
                      </Badge>
                    </span>
                    <span className="tabular text-right font-mono text-xs text-fg-faint">
                      {backup.size_bytes > 0 ? formatBytes(backup.size_bytes) : '—'}
                    </span>
                    <span className="tabular text-right font-mono text-xs text-fg-faint">
                      {duration === null ? '—' : `${Math.round(duration / 1_000)}s`}
                    </span>
                    <span className="text-xs text-fg-faint">{backup.trigger}</span>
                    <span className="flex justify-end">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={backup.status !== 'completed'}
                        onClick={() => setConfirmRestore(backup)}
                      >
                        Restore
                      </Button>
                    </span>
                  </div>
                )
              })
            )}
          </div>
        </div>
      </Card>

      <ConfirmDialog
        open={confirmRestore !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmRestore(null)
        }}
        title="Restore this backup?"
        description={
          confirmRestore
            ? `This replaces the live database with the snapshot from ${formatTimestamp(confirmRestore.started_at)}. Everything written since then is lost, and the API and workers are down for several minutes. In this preview build nothing is actually restored — the request is only recorded.`
            : ''
        }
        confirmLabel="Restore database"
        destructive
        pending={restore.isPending}
        onConfirm={() => {
          if (confirmRestore) restore.mutate(confirmRestore.id)
          setConfirmRestore(null)
        }}
      />
    </>
  )
}
