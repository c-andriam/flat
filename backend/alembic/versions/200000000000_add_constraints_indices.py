"""add constraints indices

Revision ID: 200000000000
Revises: 17abe753dbc6
Create Date: 2026-08-08 19:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '200000000000'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Utilisation de IF NOT EXISTS car SQLAlchemy crée parfois ces index
    # automatiquement via index=True dans la déclaration du modèle.
    op.execute("CREATE INDEX IF NOT EXISTS ix_actions_project_id ON actions (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_relance_logs_responsable_id ON relance_logs (responsable_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_relance_logs_responsable_id")
    op.execute("DROP INDEX IF EXISTS ix_actions_project_id")
