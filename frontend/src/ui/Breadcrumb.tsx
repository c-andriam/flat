import { Link } from 'react-router-dom'
import { Fragment } from 'react'

import { IconChevronRight } from './Icon'

export interface BreadcrumbItem {
  label: string
  to?: string
}

export function Breadcrumb({ items }: { items: BreadcrumbItem[] }) {
  return (
    <nav aria-label="Fil d'Ariane" className="mb-4">
      <ol className="flex list-none items-center gap-2 overflow-x-auto whitespace-nowrap p-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {items.map((item, index) => (
          <Fragment key={`${item.label}-${index}`}>
            <li className="flex items-center gap-2 text-[13px]">
              {item.to ? (
                <Link
                  to={item.to}
                  className="text-fg-muted no-underline transition-colors hover:text-fg"
                >
                  {item.label}
                </Link>
              ) : (
                <span className="font-medium text-fg" aria-current="page">
                  {item.label}
                </span>
              )}
            </li>
            {index < items.length - 1 ? (
              <IconChevronRight size={14} className="shrink-0 text-fg-subtle" />
            ) : null}
          </Fragment>
        ))}
      </ol>
    </nav>
  )
}
