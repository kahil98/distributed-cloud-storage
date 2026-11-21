"""Add account quotas and active upload reservations."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0002_quotas"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    inspector = inspect(op.get_bind())
    if "quota_bytes" not in {column["name"] for column in inspector.get_columns("users")}:
        op.add_column("users", sa.Column("quota_bytes", sa.BigInteger(), nullable=True,
                                          server_default="5368709120"))
    if "user_quota_reservations" not in inspector.get_table_names():
        op.create_table(
            "user_quota_reservations",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("bytes_reserved", sa.BigInteger(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_user_quota_reservations_user_id", "user_quota_reservations", ["user_id"])
        op.create_index("ix_user_quota_reservations_expires_at", "user_quota_reservations", ["expires_at"])


def downgrade():
    inspector = inspect(op.get_bind())
    if "user_quota_reservations" in inspector.get_table_names():
        op.drop_table("user_quota_reservations")
    if "quota_bytes" in {column["name"] for column in inspector.get_columns("users")}:
        op.drop_column("users", "quota_bytes")
