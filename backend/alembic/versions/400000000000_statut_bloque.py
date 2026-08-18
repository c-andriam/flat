"""ajoute le statut BLOQUE a l'enumeration actionstatus

Revision ID: 400000000000
Revises: 300000000000
Create Date: 2026-08-18 14:00:00.000000

Le code couleur des classeurs de suivi distingue Planifie / Realise / Bloque,
mais l'enumeration ne connaissait que a_faire / en_cours / en_retard / termine :
une action a l'arret etait indiscernable d'une action simplement en retard.

`ALTER TYPE ... ADD VALUE` ne peut pas s'executer dans la transaction ouverte
par Alembic (la nouvelle valeur ne serait pas visible avant le COMMIT), d'ou
le bloc autocommit.
"""
from typing import Sequence, Union

from alembic import op

revision: str = '400000000000'
down_revision: Union[str, None] = '300000000000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE actionstatus ADD VALUE IF NOT EXISTS 'BLOQUE'")


def downgrade() -> None:
    # PostgreSQL ne sait pas retirer une valeur d'un type enum : il faudrait
    # recreer le type et reecrire la colonne. Les actions BLOQUE sont donc
    # d'abord ramenees a EN_COURS, puis le type est reconstruit sans la valeur.
    op.execute("UPDATE actions SET status = 'EN_COURS' WHERE status = 'BLOQUE'")
    op.execute("ALTER TYPE actionstatus RENAME TO actionstatus_old")
    op.execute(
        "CREATE TYPE actionstatus AS ENUM "
        "('A_FAIRE', 'EN_COURS', 'EN_RETARD', 'TERMINE')"
    )
    op.execute(
        "ALTER TABLE actions ALTER COLUMN status DROP DEFAULT, "
        "ALTER COLUMN status TYPE actionstatus USING status::text::actionstatus, "
        "ALTER COLUMN status SET DEFAULT 'A_FAIRE'"
    )
    op.execute("DROP TYPE actionstatus_old")
