import { Link } from 'react-router-dom'

import { useAuth } from '@/auth/useAuth'
import { useRealtime } from '@/hooks/useRealtime'
import { cn } from '@/lib/cn'
import { initials } from '@/lib/format'
import { USER_ROLE_LABELS } from '@/api/types'
import { IconLogOut, IconSearch, IconWifi } from '@/ui/Icon'
import { ThemeToggle } from '../ThemeToggle'

const REALTIME_LABELS = {
  idle: 'Temps réel inactif',
  connecting: 'Connexion au temps réel…',
  open: 'Temps réel connecté',
  closed: 'Temps réel interrompu — reconnexion en cours',
} as const

export function AppHeader({ onOpenPalette }: { onOpenPalette: () => void }) {
  const { user, isAuthenticated, logout, login } = useAuth()
  const realtime = useRealtime()

  return (
    <header className="sticky top-0 z-50 flex h-16 items-center justify-between gap-4 border-b border-line bg-surface px-4 transition-colors duration-300 sm:px-6">
      <Link
        to="/"
        className="flex items-center gap-3 text-fg no-underline transition-[color,transform] duration-200 hover:scale-[1.02] hover:text-accent"
      >
        <span className="text-[15px] font-bold tracking-[-0.01em]">DSI TRIMETA</span>
        <span className="h-5 w-px bg-line" />
        <span className="hidden text-sm font-normal text-fg-muted sm:inline">
          Gestion de Projet
        </span>
      </Link>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onOpenPalette}
          className="hidden cursor-pointer items-center gap-2 rounded-[6px] border border-line bg-canvas px-3 py-1.5 text-[13px] text-fg-subtle transition-colors hover:border-fg-subtle hover:text-fg-muted sm:flex"
          aria-label="Ouvrir la recherche"
        >
          <IconSearch size={14} />
          <span>Rechercher</span>
          <kbd className="ml-2 rounded-[4px] border border-line bg-surface px-1.5 py-px font-sans text-[11px]">
            Ctrl K
          </kbd>
        </button>

        {isAuthenticated ? (
          <span
            title={REALTIME_LABELS[realtime]}
            className={cn(
              'hidden h-9 w-9 items-center justify-center rounded-[6px] border border-line sm:flex',
              realtime === 'open' && 'text-success',
              realtime === 'connecting' && 'animate-skeleton text-warning',
              (realtime === 'closed' || realtime === 'idle') && 'text-fg-subtle',
            )}
          >
            <IconWifi size={16} />
            <span className="sr-only">{REALTIME_LABELS[realtime]}</span>
          </span>
        ) : null}

        <ThemeToggle />

        {isAuthenticated && user ? (
          <div className="flex items-center gap-2">
            <div
              title={`${user.display_name} — ${USER_ROLE_LABELS[user.role]}`}
              className="flex h-9 w-9 items-center justify-center rounded-full bg-accent-subtle text-[12px] font-bold text-accent"
            >
              {initials(user.display_name)}
            </div>
            <button
              type="button"
              onClick={logout}
              aria-label="Se déconnecter"
              title="Se déconnecter"
              className="flex h-9 w-9 cursor-pointer items-center justify-center rounded-[6px] border border-line bg-transparent text-fg-muted transition-colors hover:bg-surface-hover hover:text-danger"
            >
              <IconLogOut size={16} />
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={login}
            className="cursor-pointer rounded-[6px] border border-line bg-canvas px-3 py-1.5 text-[13px] font-semibold text-fg transition-colors hover:bg-surface-hover"
          >
            Se connecter
          </button>
        )}
      </div>
    </header>
  )
}
