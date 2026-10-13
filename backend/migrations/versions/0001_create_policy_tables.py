"""Create policy document and vector chunk tables."""

from alembic import op

from backend.app.models.policy import PolicyChunk, PolicyDocument

revision = "0001_policy_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("CREATE SCHEMA IF NOT EXISTS insurance")
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    PolicyDocument.__table__.create(bind=connection, checkfirst=True)
    PolicyChunk.__table__.create(bind=connection, checkfirst=True)


def downgrade() -> None:
    PolicyChunk.__table__.drop(bind=op.get_bind(), checkfirst=True)
    PolicyDocument.__table__.drop(bind=op.get_bind(), checkfirst=True)
