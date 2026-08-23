import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'

import { useActions, useProjects, useResponsables } from '@/api/queries'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useScrollLock } from '@/hooks/useScrollLock'
import { useAuth } from '@/auth/useAuth'
import { cn } from '@/lib/cn'
import {
  IconActivity,
  IconClose,
  IconFolder,
  IconSearch,
  IconUsers,
  type IconProps,
} from '@/ui/Icon'
import { NAV_ENTRIES } from './layout/navigation'
import type { ComponentType } from 'react'

interface Entry {
  id: string
  label: string
  hint?: string
  group: string
  icon: ComponentType<IconProps>
  to: string
}

function matches(entry: { label: string; keywords?: string[] }, query: string): boolean {
  const needle = query.trim().toLowerCase()
  if (!needle) return true
  if (entry.label.toLowerCase().includes(needle)) return true
  return (entry.keywords ?? []).some((keyword) => keyword.toLowerCase().includes(needle))
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const { isAuthenticated } = useAuth()
  const [query, setQuery] = useState('')
  const [highlight, setHighlight] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const debounced = useDebouncedValue(query, 250)
  const searching = debounced.trim().length >= 2

  useScrollLock(open)

  // Les recherches distantes ne partent qu'à partir de deux caractères :
  // en dessous, la liste ramènerait tout le portefeuille à chaque frappe.
  const enabled = open && isAuthenticated && searching
  const projectsQuery = useProjects(enabled ? { limit: 5 } : {})
  const actionsQuery = useActions(enabled ? { search: debounced, limit: 5 } : { limit: 0 })
  const responsablesQuery = useResponsables(enabled ? { limit: 100 } : {})

  const entries = useMemo<Entry[]>(() => {
    const navEntries: Entry[] = NAV_ENTRIES.filter((entry) => matches(entry, debounced)).map(
      (entry) => ({
        id: `nav:${entry.to}`,
        label: entry.label,
        group: 'Navigation',
        icon: entry.icon,
        to: entry.to,
      }),
    )

    if (!enabled) return navEntries

    const needle = debounced.trim().toLowerCase()

    const projectEntries: Entry[] = (projectsQuery.data?.items ?? [])
      .filter(
        (project) =>
          project.code.toLowerCase().includes(needle) ||
          project.name.toLowerCase().includes(needle),
      )
      .slice(0, 5)
      .map((project) => ({
        id: `project:${project.id}`,
        label: `${project.code} — ${project.name}`,
        hint: project.is_active ? 'Projet actif' : 'Projet archivé',
        group: 'Projets',
        icon: IconFolder,
        to: `/projets/${project.id}`,
      }))

    const actionEntries: Entry[] = (actionsQuery.data?.items ?? []).slice(0, 5).map((action) => ({
      id: `action:${action.id}`,
      label: `${action.numero} — ${action.description}`,
      hint: action.resp_suivi ?? undefined,
      group: 'Actions',
      icon: IconActivity,
      to: `/actions?search=${encodeURIComponent(action.numero)}`,
    }))

    const responsableEntries: Entry[] = (responsablesQuery.data?.items ?? [])
      .filter((responsable) => responsable.display_name.toLowerCase().includes(needle))
      .slice(0, 5)
      .map((responsable) => ({
        id: `responsable:${responsable.id}`,
        label: responsable.display_name,
        hint: responsable.email ?? 'Sans email',
        group: 'Responsables',
        icon: IconUsers,
        to: `/responsables?q=${encodeURIComponent(responsable.display_name)}`,
      }))

    return [...navEntries, ...projectEntries, ...actionEntries, ...responsableEntries]
  }, [debounced, enabled, projectsQuery.data, actionsQuery.data, responsablesQuery.data])

  useEffect(() => {
    setHighlight(0)
  }, [debounced])

  useEffect(() => {
    if (!open) {
      setQuery('')
      return
    }
    const timer = window.setTimeout(() => inputRef.current?.focus(), 30)
    return () => window.clearTimeout(timer)
  }, [open])

  if (!open) return null

  const go = (entry: Entry | undefined) => {
    if (!entry) return
    onClose()
    void navigate(entry.to)
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
    } else if (event.key === 'ArrowDown') {
      event.preventDefault()
      setHighlight((current) => (entries.length === 0 ? 0 : (current + 1) % entries.length))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setHighlight((current) =>
        entries.length === 0 ? 0 : (current - 1 + entries.length) % entries.length,
      )
    } else if (event.key === 'Enter') {
      event.preventDefault()
      go(entries[highlight])
    }
  }

  let lastGroup = ''

  return createPortal(
    <div className="fixed inset-0 z-[8500]">
      <div
        className="animate-overlay-in fixed inset-0 cursor-pointer bg-[var(--overlay)]"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Palette de commandes"
        onKeyDown={onKeyDown}
        className={cn(
          'animate-dialog-in fixed left-1/2 top-[18%] flex w-full max-w-[600px] -translate-x-1/2 flex-col',
          'overflow-hidden rounded-[12px] border border-line bg-surface shadow-overlay',
          'max-md:top-0 max-md:h-dvh max-md:max-w-full max-md:rounded-none max-md:border-none',
        )}
      >
        <div className="flex h-14 shrink-0 items-center border-b border-line px-4">
          <IconSearch size={20} className="mr-3 shrink-0 text-fg-subtle" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Rechercher un projet, une action, un responsable…"
            autoComplete="off"
            spellCheck={false}
            className="flex-1 border-none bg-transparent p-0 text-base text-fg outline-none placeholder:text-fg-subtle"
          />
          <button
            type="button"
            onClick={onClose}
            aria-label="Fermer"
            className="ml-2 flex cursor-pointer items-center justify-center rounded-[6px] border-none bg-transparent p-1 text-fg-subtle transition-colors hover:bg-surface-hover hover:text-fg"
          >
            <IconClose size={18} />
          </button>
        </div>

        <div className="max-h-[400px] flex-1 overflow-y-auto max-md:max-h-none">
          {entries.length === 0 ? (
            <p className="px-4 py-10 text-center text-[13px] text-fg-muted">
              {searching ? 'Aucun résultat.' : 'Tapez au moins deux caractères pour rechercher.'}
            </p>
          ) : (
            <ul className="list-none p-2">
              {entries.map((entry, index) => {
                const showGroup = entry.group !== lastGroup
                lastGroup = entry.group
                const Icon = entry.icon
                return (
                  <li key={entry.id}>
                    {showGroup ? (
                      <p className="px-2 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-[0.05em] text-fg-subtle">
                        {entry.group}
                      </p>
                    ) : null}
                    <button
                      type="button"
                      onMouseEnter={() => setHighlight(index)}
                      onClick={() => go(entry)}
                      className={cn(
                        'flex w-full cursor-pointer items-center gap-3 rounded-[6px] border-none px-2 py-2 text-left transition-colors',
                        index === highlight ? 'bg-accent-subtle text-accent' : 'bg-transparent text-fg',
                      )}
                    >
                      <Icon size={16} className="shrink-0 opacity-80" />
                      <span className="min-w-0 flex-1 truncate text-[13px]">{entry.label}</span>
                      {entry.hint ? (
                        <span className="shrink-0 truncate text-[11px] text-fg-subtle">
                          {entry.hint}
                        </span>
                      ) : null}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>

        <div className="flex shrink-0 items-center justify-end gap-4 border-t border-line bg-canvas px-4 py-3">
          {[
            { keys: ['↑', '↓'], label: 'Naviguer' },
            { keys: ['Entrée'], label: 'Ouvrir' },
            { keys: ['Échap'], label: 'Fermer' },
          ].map((hint) => (
            <span key={hint.label} className="flex items-center gap-1.5 text-[12px] text-fg-muted">
              {hint.keys.map((key) => (
                <kbd
                  key={key}
                  className="rounded-[4px] border border-line bg-surface px-1.5 py-0.5 font-sans text-[11px]"
                >
                  {key}
                </kbd>
              ))}
              {hint.label}
            </span>
          ))}
        </div>
      </div>
    </div>,
    document.body,
  )
}
