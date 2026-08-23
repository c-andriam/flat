import { useState } from 'react'
import { Outlet } from 'react-router-dom'

import { CommandPalette } from '@/components/CommandPalette'
import { useHotkey } from '@/hooks/useHotkey'
import { AppFooter } from './AppFooter'
import { AppHeader } from './AppHeader'
import { RouteProgress } from './RouteProgress'

/** Coquille commune : en-tête, contenu, pied de page, palette Ctrl+K. */
export function RootLayout() {
  const [paletteOpen, setPaletteOpen] = useState(false)

  useHotkey({ key: 'k', ctrlOrMeta: true, allowInInput: true }, (event) => {
    event.preventDefault()
    setPaletteOpen((open) => !open)
  })

  return (
    <div className="flex min-h-dvh flex-col">
      <RouteProgress />
      <AppHeader onOpenPalette={() => setPaletteOpen(true)} />
      <Outlet />
      <AppFooter />
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  )
}
