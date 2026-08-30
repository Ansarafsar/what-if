"""initial core tables: scenarios, scenario_inputs, reality_states

Revision ID: 0001_initial_core
Revises:
Create Date: 2026-08-25

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001_initial_core"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _state_json_type() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "scenarios",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("raw_input", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(50), nullable=False, server_default="general"),
        sa.Column("status", sa.String(50), nullable=False, server_default="created"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "scenario_inputs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "scenario_id",
            sa.Uuid(),
            sa.ForeignKey("scenarios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("input_type", sa.String(50), nullable=False, server_default="initial"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_scenario_inputs_scenario_id", "scenario_inputs", ["scenario_id"])

    op.create_table(
        "reality_states",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "scenario_id",
            sa.Uuid(),
            sa.ForeignKey("scenarios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("state_json", _state_json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_reality_states_scenario_id", "reality_states", ["scenario_id"])


def downgrade() -> None:
    op.drop_table("reality_states")
    op.drop_table("scenario_inputs")
    op.drop_table("scenarios")
