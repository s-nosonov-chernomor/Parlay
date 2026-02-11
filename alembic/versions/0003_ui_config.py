# alembic/versions/0003_ui_config.py
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0003_ui_config"
down_revision = "0002_reading_partitions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ----------------------------
    # 1) ui_bindings: topic nullable + source
    # ----------------------------
    # topic теперь может быть NULL (для computed/virtual bind_key)
    op.alter_column("ui_bindings", "topic", existing_type=sa.Text(), nullable=True)

    # source: откуда берём значение для bind_key
    # mqtt | computed | constant | schedule | priva
    op.add_column(
        "ui_bindings",
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'mqtt'")),
    )

    # небольшие индексы для быстрых выборок
    op.create_index("ix_ui_elements_page", "ui_elements", ["page"])
    op.create_index("ix_ui_bindings_topic", "ui_bindings", ["topic"])
    op.create_index("ix_ui_bindings_ui_id", "ui_bindings", ["ui_id"])

    # ----------------------------
    # 2) ui_element_state: состояние режима на элемент
    # ----------------------------
    op.create_table(
        "ui_element_state",
        sa.Column("ui_id", sa.Text(), primary_key=True),
        sa.Column("mode_requested", sa.Text(), nullable=False),  # WEB|AUTO|PRIVA|MANUAL
        sa.Column("schedule_id", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["ui_id"], ["ui_elements.ui_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ui_element_state_mode", "ui_element_state", ["mode_requested"])
    op.create_index("ix_ui_element_state_schedule", "ui_element_state", ["schedule_id"])

    # ----------------------------
    # 3) ui_hw_sources + ui_hw_members: аппаратный переключатель режима (один на много линий)
    # ----------------------------
    op.create_table(
        "ui_hw_sources",
        sa.Column("source_id", sa.Text(), primary_key=True),  # например cabinet:SHD-12
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("manual_topic", sa.Text(), nullable=False),  # топик "авто режим"
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ui_hw_sources_manual_topic", "ui_hw_sources", ["manual_topic"])

    op.create_table(
        "ui_hw_members",
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("ui_id", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("source_id", "ui_id"),
        sa.ForeignKeyConstraint(["source_id"], ["ui_hw_sources.source_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ui_id"], ["ui_elements.ui_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ui_hw_members_ui_id", "ui_hw_members", ["ui_id"])

    # ----------------------------
    # 4) ui_priva_bindings: эталонные топики PRIVA, по которым зеркалируемся
    # ----------------------------
    op.create_table(
        "ui_priva_bindings",
        sa.Column("ui_id", sa.Text(), nullable=False),
        sa.Column("bind_key", sa.Text(), nullable=False),
        sa.Column("priva_topic", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("ui_id", "bind_key"),
        sa.ForeignKeyConstraint(["ui_id"], ["ui_elements.ui_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ui_priva_bindings_priva_topic", "ui_priva_bindings", ["priva_topic"])
    op.create_index("ix_ui_priva_bindings_ui", "ui_priva_bindings", ["ui_id"])

    # ----------------------------
    # 5) schedules + schedule_events: расписания (точки изменения в течение суток)
    # ----------------------------
    op.create_table(
        "schedules",
        sa.Column("schedule_id", sa.Text(), primary_key=True),  # schedule_1
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("tz", sa.Text(), nullable=False, server_default=sa.text("'Europe/Riga'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "schedule_events",
        sa.Column("schedule_id", sa.Text(), nullable=False),
        sa.Column("bind_key", sa.Text(), nullable=False),
        sa.Column("at_time", sa.Time(), nullable=False),  # время суток
        sa.Column("value_num", sa.Float(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("schedule_id", "bind_key", "at_time"),
        sa.ForeignKeyConstraint(["schedule_id"], ["schedules.schedule_id"], ondelete="CASCADE"),
        # Проверка: либо num, либо text, либо оба NULL (разрешим оба NULL? лучше запретить)
        sa.CheckConstraint(
            "(value_num IS NOT NULL AND value_text IS NULL) OR (value_num IS NULL AND value_text IS NOT NULL)",
            name="ck_schedule_events_value_oneof",
        ),
    )
    op.create_index("ix_schedule_events_lookup", "schedule_events", ["schedule_id", "bind_key", "at_time"])

    # ----------------------------
    # 6) Снять server_default с ui_bindings.source (чтобы не “прилипал” в DDL)
    # ----------------------------
    op.alter_column("ui_bindings", "source", server_default=None)


def downgrade() -> None:
    # В обратном порядке

    op.drop_index("ix_schedule_events_lookup", table_name="schedule_events")
    op.drop_table("schedule_events")
    op.drop_table("schedules")

    op.drop_index("ix_ui_priva_bindings_ui", table_name="ui_priva_bindings")
    op.drop_index("ix_ui_priva_bindings_priva_topic", table_name="ui_priva_bindings")
    op.drop_table("ui_priva_bindings")

    op.drop_index("ix_ui_hw_members_ui_id", table_name="ui_hw_members")
    op.drop_table("ui_hw_members")

    op.drop_index("ix_ui_hw_sources_manual_topic", table_name="ui_hw_sources")
    op.drop_table("ui_hw_sources")

    op.drop_index("ix_ui_element_state_schedule", table_name="ui_element_state")
    op.drop_index("ix_ui_element_state_mode", table_name="ui_element_state")
    op.drop_table("ui_element_state")

    op.drop_index("ix_ui_bindings_ui_id", table_name="ui_bindings")
    op.drop_index("ix_ui_bindings_topic", table_name="ui_bindings")
    op.drop_index("ix_ui_elements_page", table_name="ui_elements")

    op.drop_column("ui_bindings", "source")
    op.alter_column("ui_bindings", "topic", existing_type=sa.Text(), nullable=False)
