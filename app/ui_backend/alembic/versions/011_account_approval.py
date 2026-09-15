"""Admin approval for self-registered accounts

Revision ID: 011
Revises: 010
Create Date: 2026-09-15
"""
from alembic import op
import sqlalchemy as sa

revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade():
    # Existing accounts are approved; only new self-registrations start pending
    # (and only while Settings → Sign-up → "require approval" is on).
    op.add_column('users', sa.Column('approved', sa.Boolean(), nullable=False,
                                     server_default=sa.true()))


def downgrade():
    op.drop_column('users', 'approved')
