import { StatusBadge } from '@/components/common/StatusBadge'
import { jobStatusStyle, runtimeStyle } from '@/lib/utils/status'
import type { JobStatus, Runtime } from '@/types'

/** Job holati nishoni. */
export function JobStatusBadge({
  status,
  size = 'md',
}: {
  status: JobStatus
  size?: 'sm' | 'md' | 'lg'
}) {
  return <StatusBadge style={jobStatusStyle(status)} size={size} />
}

/** Runtime nishoni (Python ko'k, Node yashil). */
export function RuntimeBadge({ runtime, size = 'md' }: { runtime: Runtime; size?: 'sm' | 'md' }) {
  return <StatusBadge style={runtimeStyle(runtime)} size={size} />
}
