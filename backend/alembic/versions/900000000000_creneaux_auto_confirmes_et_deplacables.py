"""creneaux auto-confirmes et deplacables

Revision ID: 900000000000
Revises: 800000000000
Create Date: 2026-08-23 09:00:00.000000

Deux changements lies a l'usage reel.

1. Le statut PENDING disparait. Ouvrir un creneau vaut engagement de le tenir :
   faire valider chaque demande ajoutait une etape que le DSIO devait suivre,
   pour un refus qui n'arrivait jamais. Une demande devient donc directement
   CONFIRMED, et l'annulation reste possible des deux cotes.

2. La contrainte d'unicite devient differable. Deplacer une plage de 9h00-9h30
   vers 9h15-9h45 fait passer, ligne a ligne, par un etat ou deux creneaux
   partagent le meme horaire. Verifiee immediatement, la contrainte rejetait le
   deplacement ; verifiee au COMMIT, elle ne voit que l'etat final.
"""
from typing import Sequence, Union

from alembic import op

revision: str = '900000000000'
down_revision: Union[str, None] = '800000000000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Les demandes en attente deviennent des rendez-vous fermes : c'est
    # exactement la regle qu'on installe, appliquee retroactivement.
    op.execute("UPDATE slots SET status = 'CONFIRMED' WHERE status = 'PENDING'")

    op.execute("ALTER TYPE slotstatus RENAME TO slotstatus_old")
    op.execute("CREATE TYPE slotstatus AS ENUM ('OPEN', 'CONFIRMED')")
    op.execute(
        "ALTER TABLE slots ALTER COLUMN status DROP DEFAULT, "
        "ALTER COLUMN status TYPE slotstatus USING status::text::slotstatus, "
        "ALTER COLUMN status SET DEFAULT 'OPEN'"
    )
    op.execute("DROP TYPE slotstatus_old")

    op.drop_constraint('uq_slot_owner_start', 'slots', type_='unique')
    op.execute(
        "ALTER TABLE slots ADD CONSTRAINT uq_slot_owner_start "
        "UNIQUE (owner_user_id, starts_at) DEFERRABLE INITIALLY DEFERRED"
    )


def downgrade() -> None:
    op.drop_constraint('uq_slot_owner_start', 'slots', type_='unique')
    op.create_unique_constraint(
        'uq_slot_owner_start', 'slots', ['owner_user_id', 'starts_at']
    )

    op.execute("ALTER TYPE slotstatus RENAME TO slotstatus_old")
    op.execute("CREATE TYPE slotstatus AS ENUM ('OPEN', 'PENDING', 'CONFIRMED')")
    op.execute(
        "ALTER TABLE slots ALTER COLUMN status DROP DEFAULT, "
        "ALTER COLUMN status TYPE slotstatus USING status::text::slotstatus, "
        "ALTER COLUMN status SET DEFAULT 'OPEN'"
    )
    op.execute("DROP TYPE slotstatus_old")
