"""spi/otd not null (default 0.0) + contrainte unique (project_id, numero)

Revision ID: a1b2c3d4e5f6
Revises: 17abe753dbc6
Create Date: 2026-08-07 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '17abe753dbc6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Backfill des lignes existantes avant d'ajouter la contrainte NOT NULL
    op.execute("UPDATE actions SET spi = 0.0 WHERE spi IS NULL")
    op.execute("UPDATE actions SET otd = 0.0 WHERE otd IS NULL")

    op.alter_column(
        "actions", "spi",
        existing_type=sa.Float(),
        nullable=False,
        server_default="0.0",
    )
    op.alter_column(
        "actions", "otd",
        existing_type=sa.Float(),
        nullable=False,
        server_default="0.0",
    )

    op.create_unique_constraint(
        "uq_action_project_numero", "actions", ["project_id", "numero"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_action_project_numero", "actions", type_="unique")
    op.alter_column("actions", "otd", existing_type=sa.Float(), nullable=True, server_default=None)
    op.alter_column("actions", "spi", existing_type=sa.Float(), nullable=True, server_default=None)
