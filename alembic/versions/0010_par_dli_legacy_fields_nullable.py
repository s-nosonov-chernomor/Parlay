from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_par_dli_legacy_nulls"
down_revision = "0009_par_dli_dli_first_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # На всякий случай заполним пустые значения нулями
    op.execute("""
        UPDATE ui_par_dli_config
        SET ppfd_deadband_umol = 0
        WHERE ppfd_deadband_umol IS NULL
    """)

    op.execute("""
        UPDATE ui_par_dli_config
        SET dli_carryover_mol = 0
        WHERE dli_carryover_mol IS NULL
    """)

    # Старые поля делаем необязательными
    op.alter_column(
        "ui_par_dli_config",
        "ppfd_deadband_umol",
        existing_type=sa.Float(),
        nullable=True,
    )

    op.alter_column(
        "ui_par_dli_config",
        "dli_carryover_mol",
        existing_type=sa.Float(),
        nullable=True,
    )


def downgrade() -> None:
    # Перед возвратом NOT NULL снова заполним пустые значения
    op.execute("""
        UPDATE ui_par_dli_config
        SET ppfd_deadband_umol = 0
        WHERE ppfd_deadband_umol IS NULL
    """)

    op.execute("""
        UPDATE ui_par_dli_config
        SET dli_carryover_mol = 0
        WHERE dli_carryover_mol IS NULL
    """)

    op.alter_column(
        "ui_par_dli_config",
        "ppfd_deadband_umol",
        existing_type=sa.Float(),
        nullable=False,
    )

    op.alter_column(
        "ui_par_dli_config",
        "dli_carryover_mol",
        existing_type=sa.Float(),
        nullable=False,
    )