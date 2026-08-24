import type { ReactNode } from 'react'

import { cn } from '@/lib/cn'
import { IconChevronDown, IconChevronUp } from './Icon'
import { SkeletonRows } from './Skeleton'

export interface Column<T> {
  /** Identifiant stable de la colonne. */
  key: string
  header: ReactNode
  render: (row: T) => ReactNode
  /** Classes appliquées à la cellule et à l'en-tête (largeur, alignement). */
  className?: string
  /** Masquer la colonne sous 768 px — pour les informations secondaires. */
  hideOnMobile?: boolean
  /**
   * Clé de tri envoyée à l'API quand l'en-tête est cliqué.
   *
   * Absente, la colonne n'est pas triable. Le tri est délégué au serveur :
   * trier les seules lignes reçues réordonnerait une page sur onze, ce qui
   * donnerait un classement faux.
   */
  sortKey?: string
}

export interface DataTableProps<T> {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  loading?: boolean
  /** Rendu lorsque `rows` est vide et que le chargement est terminé. */
  empty?: ReactNode
  onRowClick?: (row: T) => void
  /** Clé de tri active, telle que renvoyée par `Column.sortKey`. */
  sort?: string | null
  sortOrder?: 'asc' | 'desc'
  /** Appelé au clic sur un en-tête triable. */
  onSort?: (key: string) => void
  className?: string
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading = false,
  empty,
  onRowClick,
  sort = null,
  sortOrder = 'asc',
  onSort,
  className,
}: DataTableProps<T>) {
  if (!loading && rows.length === 0 && empty) {
    return <>{empty}</>
  }

  return (
    <div className={cn('overflow-x-auto rounded-[8px] border border-line bg-surface', className)}>
      <table className="w-full border-collapse text-left text-[13px]">
        <thead>
          <tr className="bg-inset/60">
            {columns.map((column) => {
              const triable = Boolean(column.sortKey && onSort)
              const actif = triable && column.sortKey === sort
              return (
                <th
                  key={column.key}
                  scope="col"
                  // `aria-sort` est ce qui annonce le classement à un lecteur
                  // d'écran : la flèche seule ne lui dit rien.
                  aria-sort={actif ? (sortOrder === 'asc' ? 'ascending' : 'descending') : undefined}
                  className={cn(
                    'whitespace-nowrap px-4 py-2.5 text-[11px] font-semibold uppercase tracking-[0.04em] text-fg-muted',
                    column.hideOnMobile && 'hidden md:table-cell',
                    column.className,
                  )}
                >
                  {triable ? (
                    <button
                      type="button"
                      onClick={() => onSort?.(column.sortKey as string)}
                      className={cn(
                        'flex cursor-pointer items-center gap-1 border-none bg-transparent p-0 text-[11px] font-semibold uppercase tracking-[0.04em] transition-colors',
                        actif ? 'text-fg' : 'text-fg-muted hover:text-fg',
                      )}
                    >
                      {column.header}
                      {actif ? (
                        sortOrder === 'asc' ? (
                          <IconChevronUp size={12} />
                        ) : (
                          <IconChevronDown size={12} />
                        )
                      ) : (
                        // Repère permanent : sans lui, rien ne distingue une
                        // colonne triable d'une colonne figée avant le survol.
                        <IconChevronDown size={12} className="opacity-30" />
                      )}
                    </button>
                  ) : (
                    column.header
                  )}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <SkeletonRows rows={6} columns={columns.length} />
          ) : (
            rows.map((row) => (
              <tr
                key={rowKey(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={cn(
                  'border-t border-line-subtle transition-colors',
                  onRowClick && 'cursor-pointer hover:bg-surface-hover',
                )}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={cn(
                      'px-4 py-3 align-middle text-fg',
                      column.hideOnMobile && 'hidden md:table-cell',
                      column.className,
                    )}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
