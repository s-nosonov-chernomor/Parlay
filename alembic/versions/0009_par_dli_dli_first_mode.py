from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_par_dli_dli_first_mode"
down_revision = "0008_line_power_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ui_par_dli_config",
        sa.Column("light_end_time", sa.Time(), nullable=False, server_default=sa.text("'23:59:59'")),
    )
    op.add_column(
        "ui_par_dli_config",
        sa.Column("agro_day_start_time", sa.Time(), nullable=False, server_default=sa.text("'00:00:00'")),
    )

    op.add_column(
        "ui_par_dli_config",
        sa.Column("ppfd_min_umol", sa.Float(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "ui_par_dli_config",
        sa.Column("ppfd_max_umol", sa.Float(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "ui_par_dli_config",
        sa.Column("ppfd_deadband_umol", sa.Float(), nullable=False, server_default=sa.text("25")),
    )

    op.add_column(
        "ui_par_dli_config",
        sa.Column("dli_carryover_mol", sa.Float(), nullable=False, server_default=sa.text("0")),
    )

    op.add_column(
        "ui_par_dli_config",
        sa.Column("ramp_up_s", sa.Integer(), nullable=False, server_default=sa.text("1800")),
    )
    op.add_column(
        "ui_par_dli_config",
        sa.Column("max_pwm_step_pct", sa.Integer(), nullable=False, server_default=sa.text("10")),
    )

    # backfill из старых полей
    op.execute("""
        UPDATE ui_par_dli_config
        SET
            light_end_time = off_window_end,
            agro_day_start_time = start_time,
            ppfd_min_umol = ppfd_setpoint_umol,
            ppfd_max_umol = ppfd_setpoint_umol,
            ppfd_deadband_umol = par_deadband_umol,
            dli_carryover_mol = 0,
            ramp_up_s = 1800,
            max_pwm_step_pct = 10
    """)

    op.create_check_constraint(
        "ck_par_dli_cfg_ppfd_range",
        "ui_par_dli_config",
        "ppfd_max_umol >= ppfd_min_umol",
    )
    op.create_check_constraint(
        "ck_par_dli_cfg_ppfd_min_ge0",
        "ui_par_dli_config",
        "ppfd_min_umol >= 0",
    )
    op.create_check_constraint(
        "ck_par_dli_cfg_ppfd_max_ge0",
        "ui_par_dli_config",
        "ppfd_max_umol >= 0",
    )
    op.create_check_constraint(
        "ck_par_dli_cfg_ppfd_deadband_ge0",
        "ui_par_dli_config",
        "ppfd_deadband_umol >= 0",
    )
    op.create_check_constraint(
        "ck_par_dli_cfg_ramp_up_ge0",
        "ui_par_dli_config",
        "ramp_up_s >= 0",
    )
    op.create_check_constraint(
        "ck_par_dli_cfg_max_pwm_step_range",
        "ui_par_dli_config",
        "max_pwm_step_pct >= 1 AND max_pwm_step_pct <= 100",
    )


def downgrade() -> None:
    op.drop_constraint("ck_par_dli_cfg_max_pwm_step_range", "ui_par_dli_config", type_="check")
    op.drop_constraint("ck_par_dli_cfg_ramp_up_ge0", "ui_par_dli_config", type_="check")
    op.drop_constraint("ck_par_dli_cfg_ppfd_deadband_ge0", "ui_par_dli_config", type_="check")
    op.drop_constraint("ck_par_dli_cfg_ppfd_max_ge0", "ui_par_dli_config", type_="check")
    op.drop_constraint("ck_par_dli_cfg_ppfd_min_ge0", "ui_par_dli_config", type_="check")
    op.drop_constraint("ck_par_dli_cfg_ppfd_range", "ui_par_dli_config", type_="check")

    op.drop_column("ui_par_dli_config", "max_pwm_step_pct")
    op.drop_column("ui_par_dli_config", "ramp_up_s")
    op.drop_column("ui_par_dli_config", "dli_carryover_mol")
    op.drop_column("ui_par_dli_config", "ppfd_deadband_umol")
    op.drop_column("ui_par_dli_config", "ppfd_max_umol")
    op.drop_column("ui_par_dli_config", "ppfd_min_umol")
    op.drop_column("ui_par_dli_config", "agro_day_start_time")
    op.drop_column("ui_par_dli_config", "light_end_time")