"""Persistent daily AI request budgets."""
from alembic import op
from app import AIUsage
revision='0003_ai_usage'
down_revision='0002_task_snoozes'
branch_labels=None
depends_on=None

def upgrade():
    AIUsage.__table__.create(bind=op.get_bind(),checkfirst=True)

def downgrade():
    AIUsage.__table__.drop(bind=op.get_bind(),checkfirst=True)
