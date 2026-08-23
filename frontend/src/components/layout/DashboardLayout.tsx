import { Outlet } from 'react-router-dom'

import { RequireAuth } from '@/auth/RequireAuth'
import { UnlinkedNotice } from '@/components/UnlinkedNotice'
import { Sidebar } from './Sidebar'

/** Pleine largeur avec navigation latérale — toutes les pages de gestion. */
export function DashboardLayout() {
  return (
    <main className="flex w-full flex-1 flex-col gap-6 px-4 pb-18 pt-6 md:flex-row md:gap-8 md:px-8 md:pt-8">
      <Sidebar />
      <div className="min-w-0 flex-1">
        <RequireAuth>
          <UnlinkedNotice />
          <Outlet />
        </RequireAuth>
      </div>
    </main>
  )
}
