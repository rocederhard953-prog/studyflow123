"""Create initial StudyFlow 2.0 schema."""
from alembic import op
from app import Base
revision='0001_initial_schema'
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    Base.metadata.create_all(bind=op.get_bind())

def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())
