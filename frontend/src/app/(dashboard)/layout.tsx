import { AppShell } from '@/components/layout/AppShell'
import { AuthGuard } from '@/components/auth-guard'

/** Mijoz paneli qobig'i — sidebar + topbar + ⌘K. */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <AppShell variant="customer">{children}</AppShell>
    </AuthGuard>
  )
}
