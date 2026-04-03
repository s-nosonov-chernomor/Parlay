# alembic/versions/0008_line_power_config.py
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_line_power_config"
down_revision = "0007_source_bindings"
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
    if not _has_table("line_power_config"):
        op.create_table(
            "line_power_config",
            sa.Column("ui_id", sa.Text(), nullable=False),
            sa.Column("led_nominal_w", sa.Integer(), nullable=True),
            sa.Column("led_lamps_count", sa.Integer(), nullable=True),
            sa.Column("hps_nominal_w", sa.Integer(), nullable=True),
            sa.Column("hps_lamps_count", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("ui_id"),
            sa.ForeignKeyConstraint(["ui_id"], ["ui_elements.ui_id"], ondelete="CASCADE"),
        )

    if not _has_index("line_power_config", "ix_line_power_config_ui_id"):
        op.create_index("ix_line_power_config_ui_id", "line_power_config", ["ui_id"])


def downgrade() -> None:
    if _has_index("line_power_config", "ix_line_power_config_ui_id"):
        op.drop_index("ix_line_power_config_ui_id", table_name="line_power_config")

    if _has_table("line_power_config"):
        op.drop_table("line_power_config")