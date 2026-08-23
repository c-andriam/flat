import { ACTION_STATUS_LABELS, type ActionStatus } from '@/api/types'
import { Badge, type BadgeTone } from '@/ui/Badge'

const TONES: Record<ActionStatus, BadgeTone> = {
  a_faire: 'neutral',
  en_cours: 'blue',
  en_retard: 'orange',
  bloque: 'red',
  termine: 'green',
}

export function ActionStatusBadge({ status }: { status: ActionStatus }) {
  return <Badge tone={TONES[status]}>{ACTION_STATUS_LABELS[status]}</Badge>
}
