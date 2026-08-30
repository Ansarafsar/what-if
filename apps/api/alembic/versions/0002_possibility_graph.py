"""possibility graph + llm executions

Revision ID: 0002_possibility_graph
Revises: 0001_initial_core
Create Date: 2026-08-25

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002_possibility_graph"
down_revision: str | None = "0001_initial_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "possibility_nodes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "scenario_id",
            sa.Uuid(),
            sa.ForeignKey("scenarios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_id",
            sa.Uuid(),
            sa.ForeignKey("possibility_nodes.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("node_type", sa.String(30), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("plausibility", sa.String(20), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("node_metadata", _json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_possibility_nodes_scenario_id", "possibility_nodes", ["scenario_id"])

    op.create_table(
        "possibility_edges",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "scenario_id",
            sa.Uuid(),
            sa.ForeignKey("scenarios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("transition", sa.Text(), nullable=False),
        sa.Column("edge_metadata", _json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_possibility_edges_scenario_id", "possibility_edges", ["scenario_id"])
    op.create_index("ix_possibility_edges_source_id", "possibility_edges", ["source_id"])
    op.create_index("ix_possibility_edges_target_id", "possibility_edges", ["target_id"])

    op.create_table(
        "llm_executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("scenario_id", sa.Uuid(), nullable=True),
        sa.Column("stage", sa.String(50), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_name", sa.String(80), nullable=False),
        sa.Column("prompt_version", sa.String(10), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_llm_executions_scenario_id", "llm_executions", ["scenario_id"])


def downgrade() -> None:
    op.drop_table("llm_executions")
    op.drop_table("possibility_edges")
    op.drop_table("possibility_nodes")
