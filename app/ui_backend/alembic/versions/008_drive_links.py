"""Google Drive links and exported files

Revision ID: 008
Revises: 007
Create Date: 2026-09-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'drive_links',
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('google_email', sa.String(254), nullable=True),
        sa.Column('refresh_token', sa.Text(), nullable=False),
        sa.Column('folder_id', sa.String(128), nullable=True),
        sa.Column('auto_export', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_table(
        'drive_files',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('session_id', sa.String(36),
                  sa.ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('file_id', sa.String(128), nullable=False),
        sa.Column('folder_id', sa.String(128), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_drive_files_session_id', 'drive_files', ['session_id'])
    op.create_index('ix_drive_files_session_kind', 'drive_files', ['session_id', 'kind'], unique=True)


def downgrade():
    op.drop_table('drive_files')
    op.drop_table('drive_links')
