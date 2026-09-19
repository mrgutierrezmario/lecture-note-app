"""Demo accounts (read-only visitors)

Revision ID: 015
Revises: 014
Create Date: 2026-09-20
"""
from alembic import op
import sqlalchemy as sa

revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('is_demo', sa.Boolean(), nullable=False,
                                     server_default=sa.false()))


def downgrade():
    op.drop_column('users', 'is_demo')
