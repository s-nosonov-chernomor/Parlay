# alembic/versions/0007_source_bindings.py
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_source_bindings"
down_revision = "0006_auth_users_audit"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table_name in insp.get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        indexes = insp.get_indexes(table_name)
    except Exception:
        return False
    return any(ix.get("name") == index_name for ix in indexes)


def upgrade() -> None:
    if not _has_table("source_bindings"):
        op.create_table(
            "source_bindings",
            sa.Column("source_id", sa.Text(), nullable=False),
            sa.Column("bind_key", sa.Text(), nullable=False),
            sa.Column("topic", sa.Text(), nullable=False),
            sa.Column("value_type", sa.Text(), nullable=True),
            sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("source_id", "bind_key"),
            sa.ForeignKeyConstraint(["source_id"], ["ui_hw_sources.source_id"], ondelete="CASCADE"),
        )

    if not _has_index("source_bindings", "ix_source_bindings_source_id"):
        op.create_index("ix_source_bindings_source_id", "source_bindings", ["source_id"])

    if not _has_index("source_bindings", "ix_source_bindings_topic"):
        op.create_index("ix_source_bindings_topic", "source_bindings", ["topic"])


def downgrade() -> None:
    if _has_index("source_bindings", "ix_source_bindings_topic"):
        op.drop_index("ix_source_bindings_topic", table_name="source_bindings")

    if _has_index("source_bindings", "ix_source_bindings_source_id"):
        op.drop_index("ix_source_bindings_source_id", table_name="source_bindings")

    if _has_table("source_bindings"):
        op.drop_table("source_bindings")