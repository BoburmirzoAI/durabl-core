import { AppShell } from '@/components/layout/AppShell'
import { AuthGuard } from '@/components/auth-guard'

/** Admin paneli qobig'i — faqat `is_admin` foydalanuvchilar uchun. */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard requireAdmin>
      <AppShell variant="admin">{children}</AppShell>
    </AuthGuard>
  )
}
