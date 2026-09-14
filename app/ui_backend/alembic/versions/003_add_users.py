"""Add users table and session ownership

Revision ID: 003
Revises: 002
Create Date: 2026-09-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'users',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('username', sa.String(64), nullable=False, unique=True),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('disabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.add_column('sessions', sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True))
    op.create_index('ix_sessions_user_id', 'sessions', ['user_id'])


def downgrade():
    op.drop_index('ix_sessions_user_id', table_name='sessions')
    op.drop_column('sessions', 'user_id')
    op.drop_table('users')
