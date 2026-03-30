from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_auth_users_audit"
down_revision = "0005_par_dli_refactor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.CheckConstraint("role in ('admin','viewer')", name="ck_users_role"),
    )
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=True),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column("bind_key", sa.Text(), nullable=True),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_username", "audit_log", ["username"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_username", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")