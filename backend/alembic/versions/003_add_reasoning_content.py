"""add reasoning_content to chat_messages

Revision ID: 003_add_reasoning_content
Revises: 002_add_missing
Create Date: 2026-05-21

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003_add_reasoning_content'
down_revision: Union[str, None] = '002_add_missing'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('chat_messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reasoning_content', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('chat_messages', schema=None) as batch_op:
        batch_op.drop_column('reasoning_content')
