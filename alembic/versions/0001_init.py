# alembic/versions/0001_init.py
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "parameter",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("is_control", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_unique_constraint("uq_parameter_topic", "parameter", ["topic"])

    op.create_table(
        "reading",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("parameter_id", sa.Integer(), sa.ForeignKey("parameter.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),

        sa.Column("trigger", sa.String(length=32), nullable=True),
        sa.Column("status_source", sa.String(length=32), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("status_message", sa.Text(), nullable=True),
        sa.Column("silent_for_s", sa.Integer(), nullable=True),

        sa.Column("value_num", sa.Float(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # Критичный индекс под историю + быстрый last-by-topic (по ts desc)
    op.execute("CREATE INDEX IF NOT EXISTS ix_reading_param_ts_desc ON reading (parameter_id, ts DESC);")
    # Индекс по времени для системных задач/чисток
    op.execute("CREATE INDEX IF NOT EXISTS ix_reading_ts_desc ON reading (ts DESC);")

    op.create_table(
        "parameter_last",
        sa.Column("parameter_id", sa.Integer(), sa.ForeignKey("parameter.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("status_message", sa.Text(), nullable=True),
        sa.Column("silent_for_s", sa.Integer(), nullable=True),
        sa.Column("value_num", sa.Float(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
    )

    op.create_table(
        "command_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("topic_on", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_command_created_at ON command_log (created_at DESC);")


def downgrade() -> None:
    op.drop_table("command_log")
    op.drop_table("parameter_last")
    op.drop_table("reading")
    op.drop_table("parameter")
