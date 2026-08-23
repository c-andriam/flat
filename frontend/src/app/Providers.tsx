import { QueryClientProvider } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'

import { AuthProvider } from '@/auth/AuthProvider'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { ThemeProvider } from '@/theme/ThemeProvider'
import { ToastProvider } from '@/ui/ToastProvider'
import { createQueryClient } from './queryClient'

export function Providers({ children }: { children: ReactNode }) {
  // Créé dans un état : un client instancié au niveau module serait partagé
  // entre les rechargements à chaud, gardant du cache périmé en développement.
  const [queryClient] = useState(createQueryClient)

  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <ToastProvider>
            <AuthProvider>{children}</AuthProvider>
          </ToastProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}
