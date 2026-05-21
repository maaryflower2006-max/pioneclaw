"""Add missing fields and tables

Revision ID: 002_add_missing
Revises: 001_initial
Create Date: 2026-05-08

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_add_missing'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 创建 workspaces 表（必须在添加外键之前）
    op.create_table(
        'workspaces',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('path', sa.String(500), nullable=True, default=''),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.String(36), nullable=True),
        sa.Column('settings', sa.JSON(), nullable=True),
        sa.Column('is_default', sa.Boolean(), server_default='0'),
        sa.Column('is_active', sa.Boolean(), server_default='1'),
        sa.Column('last_active_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_workspaces_owner_id', 'workspaces', ['owner_id'], unique=False)
    op.create_index('ix_workspaces_organization_id', 'workspaces', ['organization_id'], unique=False)

    # SQLite 需要使用 batch_alter_table 来添加列和外键
    # 2. 给 users 表添加 default_workspace_id
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('default_workspace_id', sa.Integer(), nullable=True))

    # 3. 给 agents 表添加 workspace_id
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('workspace_id', sa.Integer(), nullable=True))
    op.create_index('ix_agents_workspace_id', 'agents', ['workspace_id'], unique=False)

    # 4. 给 memories 表添加 workspace_id
    with op.batch_alter_table('memories', schema=None) as batch_op:
        batch_op.add_column(sa.Column('workspace_id', sa.Integer(), nullable=True))
    op.create_index('ix_memories_workspace_id', 'memories', ['workspace_id'], unique=False)

    # 5. 给 tasks 表添加缺失字段
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('parent_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('workspace_id', sa.Integer(), nullable=True))
    op.create_index('ix_tasks_parent_id', 'tasks', ['parent_id'], unique=False)
    op.create_index('ix_tasks_workspace_id', 'tasks', ['workspace_id'], unique=False)

    # 6. 给 skills 表添加缺失字段
    with op.batch_alter_table('skills', schema=None) as batch_op:
        batch_op.add_column(sa.Column('organization_id', sa.String(36), nullable=True))
        batch_op.add_column(sa.Column('always_activate', sa.Boolean(), server_default='0'))
        batch_op.add_column(sa.Column('skill_format', sa.String(20), server_default='inline'))
        batch_op.add_column(sa.Column('dependencies', sa.JSON(), nullable=True))
    op.create_index('ix_skills_organization_id', 'skills', ['organization_id'], unique=False)

    # 7. 给 ai_model_configs 表添加缺失字段
    with op.batch_alter_table('ai_model_configs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('organization_id', sa.String(36), nullable=True))
        batch_op.add_column(sa.Column('allowed_orgs', sa.JSON(), nullable=True))
    op.create_index('ix_ai_model_configs_organization_id', 'ai_model_configs', ['organization_id'], unique=False)

    # 8. 给 organizations 表添加缺失字段
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('model_config_ids', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('settings', sa.JSON(), nullable=True))


def downgrade() -> None:
    # 按相反顺序删除

    # 8. 删除 organizations 表新增字段
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.drop_column('settings')
        batch_op.drop_column('model_config_ids')

    # 7. 删除 ai_model_configs 表新增字段
    op.drop_index('ix_ai_model_configs_organization_id', 'ai_model_configs')
    with op.batch_alter_table('ai_model_configs', schema=None) as batch_op:
        batch_op.drop_column('allowed_orgs')
        batch_op.drop_column('organization_id')

    # 6. 删除 skills 表新增字段
    op.drop_index('ix_skills_organization_id', 'skills')
    with op.batch_alter_table('skills', schema=None) as batch_op:
        batch_op.drop_column('dependencies')
        batch_op.drop_column('skill_format')
        batch_op.drop_column('always_activate')
        batch_op.drop_column('organization_id')

    # 5. 删除 tasks 表新增字段
    op.drop_index('ix_tasks_workspace_id', 'tasks')
    op.drop_index('ix_tasks_parent_id', 'tasks')
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_column('workspace_id')
        batch_op.drop_column('parent_id')

    # 4. 删除 memories 表新增字段
    op.drop_index('ix_memories_workspace_id', 'memories')
    with op.batch_alter_table('memories', schema=None) as batch_op:
        batch_op.drop_column('workspace_id')

    # 3. 删除 agents 表新增字段
    op.drop_index('ix_agents_workspace_id', 'agents')
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.drop_column('workspace_id')

    # 2. 删除 users 表新增字段
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('default_workspace_id')

    # 1. 删除 workspaces 表
    op.drop_index('ix_workspaces_organization_id', 'workspaces')
    op.drop_index('ix_workspaces_owner_id', 'workspaces')
    op.drop_table('workspaces')
