"""creneaux de rendez-vous avec le DSIO

Revision ID: 800000000000
Revises: 700000000000
Create Date: 2026-08-23 06:00:00.000000

Ajoute le role `dsio` et la table `slots`.

Un creneau est une unite atomique de 15 minutes, pas un intervalle libre :
une plage d'une heure est quatre lignes consecutives. Le chevauchement est
donc exclu par une simple contrainte UNIQUE (proprietaire, debut), sans
contrainte d'exclusion GiST — laquelle aurait exige l'extension `btree_gist`,
dont l'installation n'est pas garantie sur une base managee.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '800000000000'
down_revision: Union[str, None] = '700000000000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `ALTER TYPE ... ADD VALUE` ne peut pas s'executer dans la transaction
    # ouverte par Alembic : la valeur ne serait pas visible avant le COMMIT,
    # et la creation de table ci-dessous echouerait a la referencer.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'DSIO'")

    # Le type est cree explicitement, puis reference avec `create_type=False`
    # dans la colonne : sans ce drapeau, `create_table` emet un second
    # CREATE TYPE sans garde et la migration echoue sur « type already exists ».
    slotstatus = postgresql.ENUM(
        'OPEN', 'PENDING', 'CONFIRMED', name='slotstatus', create_type=False
    )
    slotstatus.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'slots',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('owner_user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_minutes', sa.SmallInteger(), nullable=False, server_default='15'),
        sa.Column(
            'status',
            slotstatus,
            nullable=False,
            server_default='OPEN',
        ),
        sa.Column('requested_by_user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('request_group_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('subject', sa.String(length=255), nullable=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        # La suppression d'un compte DSIO emporte ses disponibilites ; celle
        # d'un demandeur ne fait que detacher sa demande, pour ne pas effacer
        # les creneaux d'autrui.
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['requested_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('owner_user_id', 'starts_at', name='uq_slot_owner_start'),
    )

    op.create_index('ix_slots_owner_user_id', 'slots', ['owner_user_id'])
    op.create_index('ix_slots_starts_at', 'slots', ['starts_at'])
    op.create_index('ix_slots_status', 'slots', ['status'])
    op.create_index('ix_slots_requested_by_user_id', 'slots', ['requested_by_user_id'])
    op.create_index('ix_slots_request_group_id', 'slots', ['request_group_id'])
    # Index de la requete dominante : « les creneaux de ce DSIO entre deux
    # dates », emise a chaque changement de semaine dans la grille.
    op.create_index('ix_slots_owner_window', 'slots', ['owner_user_id', 'starts_at'])


def downgrade() -> None:
    for index in (
        'ix_slots_owner_window',
        'ix_slots_request_group_id',
        'ix_slots_requested_by_user_id',
        'ix_slots_status',
        'ix_slots_starts_at',
        'ix_slots_owner_user_id',
    ):
        op.drop_index(index, table_name='slots')
    op.drop_table('slots')
    op.execute('DROP TYPE IF EXISTS slotstatus')

    # PostgreSQL ne sait pas retirer une valeur d'un type enum : le type est
    # reconstruit sans `DSIO`, apres avoir retrograde les comptes concernes.
    op.execute("UPDATE users SET role = 'LECTEUR' WHERE role = 'DSIO'")
    op.execute("ALTER TYPE userrole RENAME TO userrole_old")
    op.execute("CREATE TYPE userrole AS ENUM ('ADMIN', 'RESPONSABLE_SI', 'LECTEUR')")
    op.execute(
        "ALTER TABLE users ALTER COLUMN role DROP DEFAULT, "
        "ALTER COLUMN role TYPE userrole USING role::text::userrole, "
        "ALTER COLUMN role SET DEFAULT 'LECTEUR'"
    )
    op.execute("DROP TYPE userrole_old")
