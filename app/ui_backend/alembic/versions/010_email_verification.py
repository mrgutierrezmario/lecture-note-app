"""Email verification for self-registered accounts

Revision ID: 010
Revises: 009
Create Date: 2026-09-15
"""
from alembic import op
import sqlalchemy as sa

revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade():
    # Existing accounts were created by an admin or before verification existed.
    op.add_column('users', sa.Column('email_verified', sa.Boolean(), nullable=False,
                                     server_default=sa.true()))
    # One table for emailed one-time tokens; purpose tells reset and verify apart.
    op.add_column('password_resets', sa.Column('purpose', sa.String(16), nullable=False,
                                               server_default='reset'))


def downgrade():
    op.drop_column('password_resets', 'purpose')
    op.drop_column('users', 'email_verified')
