"""node depth + expansion timestamp

Depth is indexed because expansion queries the tree by level ("what is at depth
4?") and the depth guard reads it on every expand. Everything else expansion
needs - resulting_state, path_labels - lives in the existing JSONB column.

Revision ID: 0003_node_depth
Revises: 0002_possibility_graph
Create Date: 2026-08-26

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_node_depth"
down_revision: str | None = "0002_possibility_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "possibility_nodes",
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "possibility_nodes",
        sa.Column("expanded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_possibility_nodes_depth", "possibility_nodes", ["depth"])

    # Backfill from the metadata written by the graph builder. Rows created
    # before Phase 1 have no depth key and stay at 0; they also have no
    # resulting_state, so the expand route refuses them explicitly.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            UPDATE possibility_nodes
            SET depth = COALESCE((node_metadata ->> 'depth')::int, 0)
            WHERE node_metadata ? 'depth'
            """
        )


def downgrade() -> None:
    op.drop_index("ix_possibility_nodes_depth", table_name="possibility_nodes")
    op.drop_column("possibility_nodes", "expanded_at")
    op.drop_column("possibility_nodes", "depth")
