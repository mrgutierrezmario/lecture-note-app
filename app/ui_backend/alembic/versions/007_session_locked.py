"""Locked (kept) lectures

Revision ID: 007
Revises: 006
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sessions', sa.Column('locked', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('sessions', 'locked')
