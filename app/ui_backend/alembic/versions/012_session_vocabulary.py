"""Per-lecture key terms for the transcriber

Revision ID: 012
Revises: 011
Create Date: 2026-09-18
"""
from alembic import op
import sqlalchemy as sa

revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sessions', sa.Column('vocabulary', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('sessions', 'vocabulary')
