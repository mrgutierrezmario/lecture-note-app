"""User-chosen Drive folder path

Revision ID: 009
Revises: 008
Create Date: 2026-09-15
"""
from alembic import op
import sqlalchemy as sa

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('drive_links', sa.Column('folder_name', sa.String(255), nullable=False,
                                           server_default='AI Lecture Notes'))


def downgrade():
    op.drop_column('drive_links', 'folder_name')
