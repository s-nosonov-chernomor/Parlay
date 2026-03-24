from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0005_par_dli_refactor"
down_revision = "0004_par_dli"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------
    # 1) ui_element_state: add par_id
    # ---------------------------------------------------
    op.add_column(
        "ui_element_state",
        sa.Column("par_id", sa.Text(), nullable=True),
    )
    op.create_index("ix_ui_element_state_par", "ui_element_state", ["par_id"])

    # ---------------------------------------------------
    # 2) drop old ui_par_dli_state
    # ---------------------------------------------------
    try:
        op.drop_index("ix_ui_par_dli_state_local_date", table_name="ui_par_dli_state")
    except Exception:
        pass

    try:
        op.drop_table("ui_par_dli_state")
    except Exception:
        pass

    # ---------------------------------------------------
    # 3) drop old ui_par_dli_config
    # ---------------------------------------------------
    try:
        op.drop_index("ix_ui_par_dli_config_tz", table_name="ui_par_dli_config")
    except Exception:
        pass

    try:
        op.drop_table("ui_par_dli_config")
    except Exception:
        pass

    # ---------------------------------------------------
    # 4) create new ui_par_dli_config
    # ---------------------------------------------------
    op.create_table(
        "ui_par_dli_config",
        sa.Column("par_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),

        sa.Column("start_time", sa.Time(), nullable=False),

        sa.Column("ppfd_setpoint_umol", sa.Float(), nullable=False),
        sa.Column("par_deadband_umol", sa.Float(), nullable=False),

        sa.Column("dli_target_mol", sa.Float(), nullable=False),
        sa.Column("dli_cap_umol", sa.Float(), nullable=True),

        sa.Column("off_window_start", sa.Time(), nullable=False),
        sa.Column("off_window_end", sa.Time(), nullable=False),

        sa.Column("fixture_umol_100", sa.Float(), nullable=False),
        sa.Column("correction_interval_s", sa.Integer(), nullable=False),

        sa.Column("par_top_bind_key", sa.Text(), nullable=False),
        sa.Column("par_sum_bind_key", sa.Text(), nullable=False),

        sa.Column(
            "enabled_bind_keys",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "dim_bind_keys",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
        ),

        sa.Column("use_dli_cap", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("tz", sa.Text(), nullable=False, server_default=sa.text("'Europe/Riga'")),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),

        sa.PrimaryKeyConstraint("par_id"),

        sa.CheckConstraint("ppfd_setpoint_umol >= 0", name="ck_par_dli_cfg_ppfd_ge0"),
        sa.CheckConstraint("par_deadband_umol >= 0", name="ck_par_dli_cfg_deadband_ge0"),
        sa.CheckConstraint("dli_target_mol >= 0", name="ck_par_dli_cfg_dli_target_ge0"),
        sa.CheckConstraint("(dli_cap_umol IS NULL) OR (dli_cap_umol >= 0)", name="ck_par_dli_cfg_dli_cap_ge0"),
        sa.CheckConstraint("fixture_umol_100 > 0", name="ck_par_dli_cfg_fixture_gt0"),
        sa.CheckConstraint("correction_interval_s > 0", name="ck_par_dli_cfg_interval_gt0"),
    )

    op.create_index("ix_ui_par_dli_config_tz", "ui_par_dli_config", ["tz"])


def downgrade() -> None:
    # ---------------------------------------------------
    # 1) drop new ui_par_dli_config
    # ---------------------------------------------------
    op.drop_index("ix_ui_par_dli_config_tz", table_name="ui_par_dli_config")
    op.drop_table("ui_par_dli_config")

    # ---------------------------------------------------
    # 2) recreate old ui_par_dli_config
    # ---------------------------------------------------
    op.create_table(
        "ui_par_dli_config",
        sa.Column("ui_id", sa.Text(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),

        sa.Column("par_target_umol", sa.Float(), nullable=False),
        sa.Column("par_deadband_umol", sa.Float(), nullable=False),

        sa.Column("dli_target_mol", sa.Float(), nullable=False),

        sa.Column("off_window_start", sa.Time(), nullable=False),
        sa.Column("off_window_end", sa.Time(), nullable=False),

        sa.Column("fixture_umol_100", sa.Float(), nullable=False),
        sa.Column("correction_interval_s", sa.Integer(), nullable=False),

        sa.Column("par_top_bind_key", sa.Text(), nullable=False),
        sa.Column("par_sum_bind_key", sa.Text(), nullable=False),
        sa.Column("enabled_bind_key", sa.Text(), nullable=False),
        sa.Column("dim_bind_key", sa.Text(), nullable=False),

        sa.Column("use_capped_dli", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("tz", sa.Text(), nullable=False, server_default=sa.text("'Europe/Riga'")),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),

        sa.PrimaryKeyConstraint("ui_id"),
        sa.ForeignKeyConstraint(["ui_id"], ["ui_elements.ui_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ui_par_dli_config_tz", "ui_par_dli_config", ["tz"])

    # ---------------------------------------------------
    # 3) recreate old ui_par_dli_state
    # ---------------------------------------------------
    op.create_table(
        "ui_par_dli_state",
        sa.Column("ui_id", sa.Text(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),

        sa.Column("dli_raw_mol", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("dli_capped_mol", sa.Float(), nullable=False, server_default=sa.text("0")),

        sa.Column("last_calc_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sum_par_umol", sa.Float(), nullable=True),

        sa.Column("last_control_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_pwm_pct", sa.Float(), nullable=True),
        sa.Column("last_enabled", sa.Boolean(), nullable=True),

        sa.Column("target_reached_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("forced_off", sa.Boolean(), nullable=False, server_default=sa.text("false")),

        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),

        sa.PrimaryKeyConstraint("ui_id"),
        sa.ForeignKeyConstraint(["ui_id"], ["ui_elements.ui_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ui_par_dli_state_local_date", "ui_par_dli_state", ["local_date"])

    # ---------------------------------------------------
    # 4) drop par_id from ui_element_state
    # ---------------------------------------------------
    op.drop_index("ix_ui_element_state_par", table_name="ui_element_state")
    op.drop_column("ui_element_state", "par_id")