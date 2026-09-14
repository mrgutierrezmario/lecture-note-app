"""Initial migration

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sessions',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('last_notes_version', sa.Integer(), nullable=True, default=0),
        sa.Column('last_summarized_segment_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'audio_chunks',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('session_id', sa.String(36), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('received_at', sa.DateTime(), nullable=True),
        sa.Column('s3_bucket', sa.Text(), nullable=True),
        sa.Column('s3_key', sa.Text(), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('decode_ok', sa.Boolean(), nullable=True, default=False),
        sa.Column('transcribed_ok', sa.Boolean(), nullable=True, default=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('deleted_from_s3', sa.Boolean(), nullable=True, default=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(
        'ix_audio_chunks_session_chunk',
        'audio_chunks',
        ['session_id', 'chunk_index']
    )

    op.create_table(
        'transcript_segments',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('session_id', sa.String(36), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('ts_start', sa.Float(), nullable=False),
        sa.Column('ts_end', sa.Float(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(
        'ix_transcript_segments_session_created',
        'transcript_segments',
        ['session_id', 'created_at']
    )

    op.create_table(
        'notes_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('session_id', sa.String(36), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('notes_md', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(
        'ix_notes_versions_session_version',
        'notes_versions',
        ['session_id', 'version']
    )


def downgrade() -> None:
    op.drop_index('ix_notes_versions_session_version', table_name='notes_versions')
    op.drop_table('notes_versions')
    op.drop_index('ix_transcript_segments_session_created', table_name='transcript_segments')
    op.drop_table('transcript_segments')
    op.drop_index('ix_audio_chunks_session_chunk', table_name='audio_chunks')
    op.drop_table('audio_chunks')
    op.drop_table('sessions')
