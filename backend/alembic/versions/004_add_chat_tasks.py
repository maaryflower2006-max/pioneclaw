"""add chat_tasks table

Revision ID: 004_add_chat_tasks
Revises: 003_add_reasoning_content
Create Date: 2026-05-24

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004_add_chat_tasks'
down_revision: Union[str, None] = '003_add_reasoning_content'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chat_tasks',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.String(36), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('context', sa.JSON(), nullable=True),
        sa.Column('system_prompt', sa.Text(), nullable=True),
        sa.Column('model_config_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='queued'),
        sa.Column('output_chunks', sa.JSON(), nullable=True),
        sa.Column('final_response', sa.Text(), nullable=True),
        sa.Column('thinking_content', sa.Text(), nullable=True),
        sa.Column('tool_calls', sa.JSON(), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('latency_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('iterations', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_chat_tasks_user_id', 'chat_tasks', ['user_id'])
    op.create_index('ix_chat_tasks_session_id', 'chat_tasks', ['session_id'])
    op.create_foreign_key(
        'fk_chat_tasks_user_id', 'chat_tasks', 'users',
        ['user_id'], ['id']
    )
    op.create_foreign_key(
        'fk_chat_tasks_session_id', 'chat_tasks', 'chat_sessions',
        ['session_id'], ['id']
    )
    op.create_foreign_key(
        'fk_chat_tasks_model_config_id', 'chat_tasks', 'ai_model_configs',
        ['model_config_id'], ['id']
    )


def downgrade() -> None:
    op.drop_index('ix_chat_tasks_session_id', table_name='chat_tasks')
    op.drop_index('ix_chat_tasks_user_id', table_name='chat_tasks')
    op.drop_table('chat_tasks')
