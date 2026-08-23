import { Navigate, useLocation } from 'react-router-dom'

import { useAuth } from '@/auth/useAuth'
import { Button } from '@/ui/Button'
import { Card, CardBody } from '@/ui/Card'
import { IconAlert, IconLogOut } from '@/ui/Icon'

interface LocationState {
  from?: string
}

export function LoginPage() {
  const { isAuthenticated, login, error, token } = useAuth()
  const location = useLocation()
  const state = location.state as LocationState | null

  if (isAuthenticated) {
    return <Navigate to={state?.from ?? '/tableau-de-bord'} replace />
  }

  return (
    <Card className="w-full max-w-[440px]">
      <CardBody className="flex flex-col items-center gap-5 py-10 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-[12px] bg-accent-subtle text-accent">
          <IconLogOut size={22} className="rotate-180" />
        </div>

        <div>
          <h1 className="text-xl font-semibold tracking-[-0.01em] text-fg">Connexion requise</h1>
          <p className="mt-2 max-w-[34ch] text-sm leading-relaxed text-fg-muted">
            L'accès aux projets et aux actions passe par le SSO Microsoft de TRIMETA Group.
          </p>
        </div>

        {token !== null && error ? (
          <p className="flex items-start gap-2 rounded-[6px] border border-warning/30 bg-warning-subtle px-3 py-2 text-left text-[13px] text-warning">
            <IconAlert size={15} className="mt-0.5 shrink-0" />
            {error.message}
          </p>
        ) : null}

        <Button variant="primary" onClick={login} className="w-full">
          Se connecter avec Microsoft
        </Button>

        <p className="text-[12px] text-fg-subtle">
          Un compte désactivé par un administrateur ne peut pas se connecter.
        </p>
      </CardBody>
    </Card>
  )
}
