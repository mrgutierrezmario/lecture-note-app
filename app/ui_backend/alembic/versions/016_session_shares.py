"""Lecture sharing (read-only viewers) and per-user chat

Revision ID: 016
Revises: 015
Create Date: 2026-09-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '016'
down_revision = '015'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'session_shares',
        sa.Column('session_id', sa.String(36),
                  sa.ForeignKey('sessions.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_session_shares_user_id', 'session_shares', ['user_id'])
    # Chat turns belong to whoever asked, so a viewer of a shared lecture has
    # their own conversation. Existing rows belong to the lecture's owner.
    op.add_column('chat_messages', sa.Column('user_id', postgresql.UUID(as_uuid=True),
                                             sa.ForeignKey('users.id', ondelete='CASCADE'),
                                             nullable=True))
    op.execute("UPDATE chat_messages c SET user_id = s.user_id FROM sessions s WHERE s.id = c.session_id")
    op.create_index('ix_chat_messages_user_id', 'chat_messages', ['user_id'])


def downgrade():
    op.drop_index('ix_chat_messages_user_id', table_name='chat_messages')
    op.drop_column('chat_messages', 'user_id')
    op.drop_table('session_shares')
