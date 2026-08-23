import { Outlet } from 'react-router-dom'

/** Colonne centrée — accueil, connexion, page introuvable. */
export function CenteredLayout() {
  return (
    <main className="mx-auto flex w-full max-w-[1000px] flex-1 flex-col items-center justify-center px-6 pb-18 pt-14">
      <Outlet />
    </main>
  )
}
