"""Per-lecture instruction for the notes generator

Revision ID: 013
Revises: 012
Create Date: 2026-09-18
"""
from alembic import op
import sqlalchemy as sa

revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sessions', sa.Column('notes_focus', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('sessions', 'notes_focus')
