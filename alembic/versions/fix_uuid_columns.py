"""fix uuid columns to use native postgresql uuid type

Revision ID: fix_uuid_columns
Revises: e821a8f88416
Create Date: 2026-08-18 03:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'fix_uuid_columns'
down_revision: Union[str, None] = 'e821a8f88416'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Convert String UUID columns to native PostgreSQL UUID type."""
    
    # Get connection to check dialect
    conn = op.get_bind()
    
    # Only apply for PostgreSQL
    if conn.dialect.name == 'postgresql':
        # Step 1: Drop all foreign key constraints
        # We'll need to recreate them after altering column types
        
        # Helper function to safely drop constraint if it exists
        def drop_constraint_if_exists(constraint_name, table_name, constraint_type='foreignkey'):
            try:
                op.drop_constraint(constraint_name, table_name, type_=constraint_type)
            except Exception:
                pass  # Constraint doesn't exist, skip
        
        # Notifications FK
        drop_constraint_if_exists('notifications_user_id_fkey', 'notifications')
        
        # Workspaces FK
        drop_constraint_if_exists('workspaces_owner_id_fkey', 'workspaces')
        
        # Workspace members FK
        drop_constraint_if_exists('workspace_members_user_id_fkey', 'workspace_members')
        drop_constraint_if_exists('workspace_members_workspace_id_fkey', 'workspace_members')
        
        # Project members FK
        drop_constraint_if_exists('project_members_project_id_fkey', 'project_members')
        drop_constraint_if_exists('project_members_user_id_fkey', 'project_members')
        
        # Projects FK
        drop_constraint_if_exists('projects_workspace_id_fkey', 'projects')
        
        # Sections FK
        drop_constraint_if_exists('sections_project_id_fkey', 'sections')
        
        # Tags FK
        drop_constraint_if_exists('tags_project_id_fkey', 'tags')
        
        # Tasks FK
        drop_constraint_if_exists('tasks_assignee_id_fkey', 'tasks')
        drop_constraint_if_exists('tasks_project_id_fkey', 'tasks')
        drop_constraint_if_exists('tasks_reporter_id_fkey', 'tasks')
        drop_constraint_if_exists('tasks_section_id_fkey', 'tasks')
        
        # Attachments FK
        drop_constraint_if_exists('attachments_task_id_fkey', 'attachments')
        drop_constraint_if_exists('attachments_uploader_id_fkey', 'attachments')
        
        # Comments FK
        drop_constraint_if_exists('comments_task_id_fkey', 'comments')
        drop_constraint_if_exists('comments_user_id_fkey', 'comments')
        
        # Subtasks FK
        drop_constraint_if_exists('subtasks_task_id_fkey', 'subtasks')
        
        # Task dependencies FK
        drop_constraint_if_exists('task_dependencies_predecessor_task_id_fkey', 'task_dependencies')
        drop_constraint_if_exists('task_dependencies_successor_task_id_fkey', 'task_dependencies')
        
        # Task tags FK
        drop_constraint_if_exists('task_tags_tag_id_fkey', 'task_tags')
        drop_constraint_if_exists('task_tags_task_id_fkey', 'task_tags')
        
        # Time logs FK
        drop_constraint_if_exists('time_logs_task_id_fkey', 'time_logs')
        drop_constraint_if_exists('time_logs_user_id_fkey', 'time_logs')
        
        # Activity logs FK (only task_id and user_id)
        drop_constraint_if_exists('activity_logs_user_id_fkey', 'activity_logs')
        drop_constraint_if_exists('activity_logs_task_id_fkey', 'activity_logs')
        
        # Step 2: Alter all UUID columns to UUID type
        # Users table
        op.execute('ALTER TABLE users ALTER COLUMN id TYPE UUID USING id::uuid')
        
        # Workspaces table
        op.execute('ALTER TABLE workspaces ALTER COLUMN id TYPE UUID USING id::uuid')
        op.execute('ALTER TABLE workspaces ALTER COLUMN owner_id TYPE UUID USING owner_id::uuid')
        
        # Workspace members table
        op.execute('ALTER TABLE workspace_members ALTER COLUMN workspace_id TYPE UUID USING workspace_id::uuid')
        op.execute('ALTER TABLE workspace_members ALTER COLUMN user_id TYPE UUID USING user_id::uuid')
        
        # Projects table
        op.execute('ALTER TABLE projects ALTER COLUMN id TYPE UUID USING id::uuid')
        op.execute('ALTER TABLE projects ALTER COLUMN workspace_id TYPE UUID USING workspace_id::uuid')
        
        # Project members table
        op.execute('ALTER TABLE project_members ALTER COLUMN project_id TYPE UUID USING project_id::uuid')
        op.execute('ALTER TABLE project_members ALTER COLUMN user_id TYPE UUID USING user_id::uuid')
        
        # Sections table
        op.execute('ALTER TABLE sections ALTER COLUMN id TYPE UUID USING id::uuid')
        op.execute('ALTER TABLE sections ALTER COLUMN project_id TYPE UUID USING project_id::uuid')
        
        # Tags table
        op.execute('ALTER TABLE tags ALTER COLUMN id TYPE UUID USING id::uuid')
        op.execute('ALTER TABLE tags ALTER COLUMN project_id TYPE UUID USING project_id::uuid')
        
        # Tasks table
        op.execute('ALTER TABLE tasks ALTER COLUMN id TYPE UUID USING id::uuid')
        op.execute('ALTER TABLE tasks ALTER COLUMN project_id TYPE UUID USING project_id::uuid')
        op.execute('ALTER TABLE tasks ALTER COLUMN section_id TYPE UUID USING section_id::uuid')
        op.execute('ALTER TABLE tasks ALTER COLUMN assignee_id TYPE UUID USING assignee_id::uuid')
        op.execute('ALTER TABLE tasks ALTER COLUMN reporter_id TYPE UUID USING reporter_id::uuid')
        
        # Attachments table
        op.execute('ALTER TABLE attachments ALTER COLUMN id TYPE UUID USING id::uuid')
        op.execute('ALTER TABLE attachments ALTER COLUMN task_id TYPE UUID USING task_id::uuid')
        op.execute('ALTER TABLE attachments ALTER COLUMN uploader_id TYPE UUID USING uploader_id::uuid')
        
        # Comments table
        op.execute('ALTER TABLE comments ALTER COLUMN id TYPE UUID USING id::uuid')
        op.execute('ALTER TABLE comments ALTER COLUMN task_id TYPE UUID USING task_id::uuid')
        op.execute('ALTER TABLE comments ALTER COLUMN user_id TYPE UUID USING user_id::uuid')
        
        # Subtasks table
        op.execute('ALTER TABLE subtasks ALTER COLUMN id TYPE UUID USING id::uuid')
        op.execute('ALTER TABLE subtasks ALTER COLUMN task_id TYPE UUID USING task_id::uuid')
        
        # Task dependencies table
        op.execute('ALTER TABLE task_dependencies ALTER COLUMN predecessor_task_id TYPE UUID USING predecessor_task_id::uuid')
        op.execute('ALTER TABLE task_dependencies ALTER COLUMN successor_task_id TYPE UUID USING successor_task_id::uuid')
        
        # Task tags table
        op.execute('ALTER TABLE task_tags ALTER COLUMN task_id TYPE UUID USING task_id::uuid')
        op.execute('ALTER TABLE task_tags ALTER COLUMN tag_id TYPE UUID USING tag_id::uuid')
        
        # Time logs table
        op.execute('ALTER TABLE time_logs ALTER COLUMN id TYPE UUID USING id::uuid')
        op.execute('ALTER TABLE time_logs ALTER COLUMN task_id TYPE UUID USING task_id::uuid')
        op.execute('ALTER TABLE time_logs ALTER COLUMN user_id TYPE UUID USING user_id::uuid')
        
        # Notifications table
        op.execute('ALTER TABLE notifications ALTER COLUMN id TYPE UUID USING id::uuid')
        op.execute('ALTER TABLE notifications ALTER COLUMN user_id TYPE UUID USING user_id::uuid')
        
        # Activity logs table (only has task_id and user_id UUID fields)
        op.execute('ALTER TABLE activity_logs ALTER COLUMN task_id TYPE UUID USING task_id::uuid')
        op.execute('ALTER TABLE activity_logs ALTER COLUMN user_id TYPE UUID USING user_id::uuid')
        
        # Step 3: Recreate foreign key constraints
        # Notifications FK
        op.create_foreign_key('notifications_user_id_fkey', 'notifications', 'users', ['user_id'], ['id'], ondelete='CASCADE')
        
        # Workspaces FK
        op.create_foreign_key('workspaces_owner_id_fkey', 'workspaces', 'users', ['owner_id'], ['id'], ondelete='CASCADE')
        
        # Workspace members FK
        op.create_foreign_key('workspace_members_user_id_fkey', 'workspace_members', 'users', ['user_id'], ['id'], ondelete='CASCADE')
        op.create_foreign_key('workspace_members_workspace_id_fkey', 'workspace_members', 'workspaces', ['workspace_id'], ['id'], ondelete='CASCADE')
        
        # Project members FK
        op.create_foreign_key('project_members_project_id_fkey', 'project_members', 'projects', ['project_id'], ['id'], ondelete='CASCADE')
        op.create_foreign_key('project_members_user_id_fkey', 'project_members', 'users', ['user_id'], ['id'], ondelete='CASCADE')
        
        # Projects FK
        op.create_foreign_key('projects_workspace_id_fkey', 'projects', 'workspaces', ['workspace_id'], ['id'], ondelete='CASCADE')
        
        # Sections FK
        op.create_foreign_key('sections_project_id_fkey', 'sections', 'projects', ['project_id'], ['id'], ondelete='CASCADE')
        
        # Tags FK
        op.create_foreign_key('tags_project_id_fkey', 'tags', 'projects', ['project_id'], ['id'], ondelete='CASCADE')
        
        # Tasks FK
        op.create_foreign_key('tasks_assignee_id_fkey', 'tasks', 'users', ['assignee_id'], ['id'], ondelete='SET NULL')
        op.create_foreign_key('tasks_project_id_fkey', 'tasks', 'projects', ['project_id'], ['id'], ondelete='CASCADE')
        op.create_foreign_key('tasks_reporter_id_fkey', 'tasks', 'users', ['reporter_id'], ['id'], ondelete='SET NULL')
        op.create_foreign_key('tasks_section_id_fkey', 'tasks', 'sections', ['section_id'], ['id'], ondelete='CASCADE')
        
        # Attachments FK
        op.create_foreign_key('attachments_task_id_fkey', 'attachments', 'tasks', ['task_id'], ['id'], ondelete='CASCADE')
        op.create_foreign_key('attachments_uploader_id_fkey', 'attachments', 'users', ['uploader_id'], ['id'], ondelete='CASCADE')
        
        # Comments FK
        op.create_foreign_key('comments_task_id_fkey', 'comments', 'tasks', ['task_id'], ['id'], ondelete='CASCADE')
        op.create_foreign_key('comments_user_id_fkey', 'comments', 'users', ['user_id'], ['id'], ondelete='CASCADE')
        
        # Subtasks FK
        op.create_foreign_key('subtasks_task_id_fkey', 'subtasks', 'tasks', ['task_id'], ['id'], ondelete='CASCADE')
        
        # Task dependencies FK
        op.create_foreign_key('task_dependencies_predecessor_task_id_fkey', 'task_dependencies', 'tasks', ['predecessor_task_id'], ['id'], ondelete='CASCADE')
        op.create_foreign_key('task_dependencies_successor_task_id_fkey', 'task_dependencies', 'tasks', ['successor_task_id'], ['id'], ondelete='CASCADE')
        
        # Task tags FK
        op.create_foreign_key('task_tags_tag_id_fkey', 'task_tags', 'tags', ['tag_id'], ['id'], ondelete='CASCADE')
        op.create_foreign_key('task_tags_task_id_fkey', 'task_tags', 'tasks', ['task_id'], ['id'], ondelete='CASCADE')
        
        # Time logs FK
        op.create_foreign_key('time_logs_task_id_fkey', 'time_logs', 'tasks', ['task_id'], ['id'], ondelete='CASCADE')
        op.create_foreign_key('time_logs_user_id_fkey', 'time_logs', 'users', ['user_id'], ['id'], ondelete='CASCADE')
        
        # Activity logs FK (only task_id and user_id)
        op.create_foreign_key('activity_logs_user_id_fkey', 'activity_logs', 'users', ['user_id'], ['id'], ondelete='SET NULL')
        op.create_foreign_key('activity_logs_task_id_fkey', 'activity_logs', 'tasks', ['task_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    """Convert UUID columns back to VARCHAR(36)."""
    
    # Get connection to check dialect
    conn = op.get_bind()
    
    # Only apply for PostgreSQL
    if conn.dialect.name == 'postgresql':
        # Reverse all changes
        # Users table
        op.execute('ALTER TABLE users ALTER COLUMN id TYPE VARCHAR(36)')
        
        # Workspaces table
        op.execute('ALTER TABLE workspaces ALTER COLUMN id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE workspaces ALTER COLUMN owner_id TYPE VARCHAR(36)')
        
        # Workspace members table
        op.execute('ALTER TABLE workspace_members ALTER COLUMN workspace_id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE workspace_members ALTER COLUMN user_id TYPE VARCHAR(36)')
        
        # Projects table
        op.execute('ALTER TABLE projects ALTER COLUMN id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE projects ALTER COLUMN workspace_id TYPE VARCHAR(36)')
        
        # Project members table
        op.execute('ALTER TABLE project_members ALTER COLUMN project_id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE project_members ALTER COLUMN user_id TYPE VARCHAR(36)')
        
        # Sections table
        op.execute('ALTER TABLE sections ALTER COLUMN id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE sections ALTER COLUMN project_id TYPE VARCHAR(36)')
        
        # Tags table
        op.execute('ALTER TABLE tags ALTER COLUMN id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE tags ALTER COLUMN project_id TYPE VARCHAR(36)')
        
        # Tasks table
        op.execute('ALTER TABLE tasks ALTER COLUMN id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE tasks ALTER COLUMN project_id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE tasks ALTER COLUMN section_id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE tasks ALTER COLUMN assignee_id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE tasks ALTER COLUMN reporter_id TYPE VARCHAR(36)')
        
        # Attachments table
        op.execute('ALTER TABLE attachments ALTER COLUMN id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE attachments ALTER COLUMN task_id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE attachments ALTER COLUMN uploader_id TYPE VARCHAR(36)')
        
        # Comments table
        op.execute('ALTER TABLE comments ALTER COLUMN id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE comments ALTER COLUMN task_id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE comments ALTER COLUMN user_id TYPE VARCHAR(36)')
        
        # Subtasks table
        op.execute('ALTER TABLE subtasks ALTER COLUMN id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE subtasks ALTER COLUMN task_id TYPE VARCHAR(36)')
        
        # Task dependencies table
        op.execute('ALTER TABLE task_dependencies ALTER COLUMN predecessor_task_id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE task_dependencies ALTER COLUMN successor_task_id TYPE VARCHAR(36)')
        
        # Task tags table
        op.execute('ALTER TABLE task_tags ALTER COLUMN task_id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE task_tags ALTER COLUMN tag_id TYPE VARCHAR(36)')
        
        # Time logs table
        op.execute('ALTER TABLE time_logs ALTER COLUMN id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE time_logs ALTER COLUMN task_id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE time_logs ALTER COLUMN user_id TYPE VARCHAR(36)')
        
        # Notifications table
        op.execute('ALTER TABLE notifications ALTER COLUMN id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE notifications ALTER COLUMN user_id TYPE VARCHAR(36)')
        
        # Activity logs table
        op.execute('ALTER TABLE activity_logs ALTER COLUMN id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE activity_logs ALTER COLUMN user_id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE activity_logs ALTER COLUMN workspace_id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE activity_logs ALTER COLUMN project_id TYPE VARCHAR(36)')
        op.execute('ALTER TABLE activity_logs ALTER COLUMN task_id TYPE VARCHAR(36)')
