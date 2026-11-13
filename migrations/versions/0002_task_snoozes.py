"""Add durable task snoozes for My-Study 2.1."""
from alembic import op
from app import TaskSnooze
revision='0002_task_snoozes'
down_revision='0001_initial_schema'
branch_labels=None
depends_on=None

def upgrade():
    TaskSnooze.__table__.create(bind=op.get_bind(),checkfirst=True)

def downgrade():
    TaskSnooze.__table__.drop(bind=op.get_bind(),checkfirst=True)
