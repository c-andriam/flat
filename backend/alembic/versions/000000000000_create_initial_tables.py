"""create initial tables

Revision ID: 000000000000
Revises: 
Create Date: 2026-08-06 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '000000000000'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enum types
    userrole_enum = postgresql.ENUM('ADMIN', 'RESPONSABLE_SI', 'LECTEUR', name='userrole', create_type=False)
    userrole_enum.create(op.get_bind(), checkfirst=True)

    actionstatus_enum = postgresql.ENUM('A_FAIRE', 'EN_COURS', 'EN_RETARD', 'TERMINE', name='actionstatus', create_type=False)
    actionstatus_enum.create(op.get_bind(), checkfirst=True)

    syncstatus_enum = postgresql.ENUM('RUNNING', 'SUCCESS', 'FAILED', name='syncstatus', create_type=False)
    syncstatus_enum.create(op.get_bind(), checkfirst=True)

    # Tables
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('azure_object_id', sa.String(length=36), nullable=False, unique=True),
        sa.Column('email', sa.String(length=255), nullable=False, unique=True),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('role', sa.Enum('ADMIN', 'RESPONSABLE_SI', 'LECTEUR', name='userrole'), nullable=False, server_default='LECTEUR'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'responsables',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('display_name', sa.String(length=255), nullable=False, unique=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('is_mapped', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )

    op.create_table(
        'projects',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('code', sa.String(length=50), nullable=False, unique=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('source_file_path', sa.String(length=1024), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'actions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('numero', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('progress', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('deadline', sa.Date(), nullable=True),
        sa.Column('status', sa.Enum('A_FAIRE', 'EN_COURS', 'EN_RETARD', 'TERMINE', name='actionstatus'), nullable=False, server_default='A_FAIRE'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index(op.f('ix_actions_project_id'), 'actions', ['project_id'], unique=False)

    op.create_table(
        'action_responsables',
        sa.Column('action_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('actions.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('responsable_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('responsables.id', ondelete='CASCADE'), primary_key=True),
    )

    op.create_table(
        'sync_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.Enum('RUNNING', 'SUCCESS', 'FAILED', name='syncstatus'), nullable=False, server_default='RUNNING'),
        sa.Column('files_processed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
    )

    op.create_table(
        'relance_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('responsable_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('responsables.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=False),
        sa.Column('action_ids', sa.Text(), nullable=False),
        sa.Column('email_status', sa.String(length=50), nullable=False, server_default='sent'),
    )
    op.create_index(op.f('ix_relance_logs_responsable_id'), 'relance_logs', ['responsable_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_relance_logs_responsable_id'), table_name='relance_logs')
    op.drop_table('relance_logs')
    op.drop_table('sync_logs')
    op.drop_table('action_responsables')
    op.drop_index(op.f('ix_actions_project_id'), table_name='actions')
    op.drop_table('actions')
    op.drop_table('projects')
    op.drop_table('responsables')
    op.drop_table('users')
