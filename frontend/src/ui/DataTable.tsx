import type { ReactNode } from 'react'

import { cn } from '@/lib/cn'
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
}

export interface DataTableProps<T> {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  loading?: boolean
  /** Rendu lorsque `rows` est vide et que le chargement est terminé. */
  empty?: ReactNode
  onRowClick?: (row: T) => void
  className?: string
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading = false,
  empty,
  onRowClick,
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
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={cn(
                  'whitespace-nowrap px-4 py-2.5 text-[11px] font-semibold uppercase tracking-[0.04em] text-fg-muted',
                  column.hideOnMobile && 'hidden md:table-cell',
                  column.className,
                )}
              >
                {column.header}
              </th>
            ))}
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
