/** Formatages numériques partagés par les tableaux et les rapports. */

const NUMBER_FR = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 })
const DECIMAL_FR = new Intl.NumberFormat('fr-FR', {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
})

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return NUMBER_FR.format(value)
}

export function formatPercent(value: number | null | undefined, decimals = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return decimals > 0 ? `${DECIMAL_FR.format(value)} %` : `${NUMBER_FR.format(value)} %`
}

export function formatHj(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${DECIMAL_FR.format(value)} h/j`
}

/** Initiales d'un nom affiché, pour les pastilles d'avatar. */
export function initials(displayName: string): string {
  const parts = displayName.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return (parts[0] ?? '').slice(0, 2).toUpperCase()
  return `${(parts[0] ?? '')[0] ?? ''}${(parts[parts.length - 1] ?? '')[0] ?? ''}`.toUpperCase()
}

/** Couleur stable dérivée d'une chaîne — même responsable, même teinte. */
export function hueFromString(value: string): number {
  let hash = 0
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 31 + value.charCodeAt(i)) % 360
  }
  return hash
}
