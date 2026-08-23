"""rapports de fin de journee

Revision ID: a00000000000
Revises: 900000000000
Create Date: 2026-08-23 12:00:00.000000

Deux tables : un rapport par personne et par jour, et ses lignes.

`daily_report_items.label` recopie le libelle de l'action au moment de la
declaration plutot que de s'appuyer sur la jointure : une action renommee trois
mois plus tard ne doit pas reecrire ce qui a ete rapporte ce jour-la. La
reference a l'action est conservee a cote, pour le recoupement.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'a00000000000'
down_revision: Union[str, None] = '900000000000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    source = postgresql.ENUM(
        'ACTION', 'MANUAL', name='reportitemsource', create_type=False
    )
    source.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'daily_reports',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('report_date', sa.Date(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        # Un double-clic ou deux onglets ouverts creeraient sinon deux rapports
        # partiels pour la meme journee, au lieu d'un seul complet.
        sa.UniqueConstraint('user_id', 'report_date', name='uq_daily_report_user_date'),
    )
    op.create_index('ix_daily_reports_user_id', 'daily_reports', ['user_id'])
    op.create_index('ix_daily_reports_report_date', 'daily_reports', ['report_date'])
    op.create_index('ix_daily_reports_user_date', 'daily_reports', ['user_id', 'report_date'])

    op.create_table(
        'daily_report_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('report_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('action_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('source', source, nullable=False, server_default='MANUAL'),
        sa.Column('label', sa.String(length=500), nullable=False),
        sa.Column('done', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('position', sa.SmallInteger(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['report_id'], ['daily_reports.id'], ondelete='CASCADE'),
        # Supprimer une action n'efface pas la trace du travail declare : le
        # libelle a ete recopie, seule la reference disparait.
        sa.ForeignKeyConstraint(['action_id'], ['actions.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_daily_report_items_report_id', 'daily_report_items', ['report_id'])
    op.create_index('ix_daily_report_items_action_id', 'daily_report_items', ['action_id'])


def downgrade() -> None:
    op.drop_index('ix_daily_report_items_action_id', table_name='daily_report_items')
    op.drop_index('ix_daily_report_items_report_id', table_name='daily_report_items')
    op.drop_table('daily_report_items')

    op.drop_index('ix_daily_reports_user_date', table_name='daily_reports')
    op.drop_index('ix_daily_reports_report_date', table_name='daily_reports')
    op.drop_index('ix_daily_reports_user_id', table_name='daily_reports')
    op.drop_table('daily_reports')

    op.execute('DROP TYPE IF EXISTS reportitemsource')
