"""index de performance sur actions, logs et association responsables

Revision ID: 300000000000
Revises: 200000000000
Create Date: 2026-08-18 10:00:00.000000

Ces index couvrent les requetes ajoutees ou corrigees lors de l'audit :
  - filtre `overdue_only` desormais applique en SQL (deadline, progress) ;
  - filtre par statut sur /actions et bascule EN_RETARD du beat ;
  - fenetre anti-spam des relances (RelanceLog.sent_at) ;
  - tri des journaux de synchronisation (SyncLog.started_at) ;
  - recherche des actions d'un responsable : la cle primaire de
    action_responsables est (action_id, responsable_id), donc inutilisable
    pour un parcours dans le sens inverse.
"""
from typing import Sequence, Union

from alembic import op

revision: str = '300000000000'
down_revision: Union[str, None] = '200000000000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_actions_deadline ON actions (deadline)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_actions_status ON actions (status)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_actions_open_deadline "
        "ON actions (deadline) WHERE progress < 100.0"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_action_responsables_responsable_id "
        "ON action_responsables (responsable_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_relance_logs_sent_at ON relance_logs (sent_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sync_logs_started_at ON sync_logs (started_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sync_logs_started_at")
    op.execute("DROP INDEX IF EXISTS ix_relance_logs_sent_at")
    op.execute("DROP INDEX IF EXISTS ix_action_responsables_responsable_id")
    op.execute("DROP INDEX IF EXISTS ix_actions_open_deadline")
    op.execute("DROP INDEX IF EXISTS ix_actions_status")
    op.execute("DROP INDEX IF EXISTS ix_actions_deadline")
