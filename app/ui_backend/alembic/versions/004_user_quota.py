"""Per-user storage quota override

Revision ID: 004
Revises: 003
Create Date: 2026-09-13
"""
from alembic import op
import sqlalchemy as sa

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('quota_mb', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('users', 'quota_mb')
