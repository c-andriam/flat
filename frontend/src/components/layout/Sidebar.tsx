import { NavLink } from 'react-router-dom'

import { cn } from '@/lib/cn'
import { NAV_ENTRIES } from './navigation'

export function Sidebar() {
  return (
    <aside
      className={cn(
        'flex shrink-0 gap-2',
        // Mobile : rail horizontal défilant, comme l'ancienne sidebar htmx.
        'w-full flex-row overflow-x-auto border-b border-line pb-4',
        'md:w-60 md:flex-col md:overflow-visible md:border-b-0 md:pb-0',
      )}
    >
      {NAV_ENTRIES.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) =>
            cn(
              'flex shrink-0 items-center gap-3 whitespace-nowrap rounded-[6px] px-3 py-2',
              'text-sm font-medium no-underline transition-colors duration-200',
              isActive
                ? 'bg-accent-subtle font-semibold text-accent'
                : 'text-fg-muted hover:bg-surface-hover hover:text-fg',
            )
          }
        >
          <Icon size={16} className="shrink-0" />
          {label}
        </NavLink>
      ))}
    </aside>
  )
}
