import { cn } from '@/lib/cn'

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn('animate-skeleton rounded-[4px] bg-line', className)}
      aria-hidden="true"
    />
  )
}

/** Lignes de remplissage pendant le chargement d'un tableau. */
export function SkeletonRows({ rows = 5, columns = 4 }: { rows?: number; columns?: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, rowIndex) => (
        <tr key={rowIndex} className="border-t border-line-subtle">
          {Array.from({ length: columns }, (_, columnIndex) => (
            <td key={columnIndex} className="px-4 py-3">
              <Skeleton className={cn('h-3.5', columnIndex === 0 ? 'w-3/4' : 'w-1/2')} />
            </td>
          ))}
        </tr>
      ))}
    </>
  )
}
