"""Persist login throttling across gateway processes and restarts."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0003_auth_throttle"
down_revision = "0002_quotas"
branch_labels = None
depends_on = None


def upgrade():
    if "auth_rate_limits" not in inspect(op.get_bind()).get_table_names():
        op.create_table(
            "auth_rate_limits",
            sa.Column("username", sa.String(length=80), primary_key=True),
            sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade():
    if "auth_rate_limits" in inspect(op.get_bind()).get_table_names():
        op.drop_table("auth_rate_limits")
