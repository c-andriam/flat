"""horodatages en timestamptz

Revision ID: 500000000000
Revises: 400000000000
Create Date: 2026-08-18 16:00:00.000000

Les colonnes d'horodatage etaient en TIMESTAMP WITHOUT TIME ZONE alors que les
valeurs par defaut de l'ORM sont conscientes du fuseau (datetime.now(utc)).
asyncpg refuse ce couple : toute ecriture passant par l'API echouait en 500
(« can't subtract offset-naive and offset-aware datetimes »), qu'il s'agisse
d'une creation de projet, d'une creation d'action ou d'une mise a jour. Les
workers Celery, eux, fonctionnaient : psycopg2 accepte la valeur en supprimant
silencieusement le fuseau.

Les valeurs deja en base ont ete ecrites en UTC par ce meme mecanisme : la
conversion les interprete donc explicitement comme telles.
"""
from typing import Sequence, Union

from alembic import op

revision: str = '500000000000'
down_revision: Union[str, None] = '400000000000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLONNES = [
    ("projects", "created_at"),
    ("projects", "last_synced_at"),
    ("actions", "created_at"),
    ("actions", "updated_at"),
    ("responsables", "created_at"),
    ("responsables", "updated_at"),
    ("users", "created_at"),
    ("users", "last_login_at"),
    ("sync_logs", "started_at"),
    ("sync_logs", "finished_at"),
    ("relance_logs", "sent_at"),
]


def upgrade() -> None:
    for table, colonne in COLONNES:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {colonne} "
            f"TYPE TIMESTAMP WITH TIME ZONE "
            f"USING {colonne} AT TIME ZONE 'UTC'"
        )


def downgrade() -> None:
    for table, colonne in COLONNES:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {colonne} "
            f"TYPE TIMESTAMP WITHOUT TIME ZONE "
            f"USING {colonne} AT TIME ZONE 'UTC'"
        )
