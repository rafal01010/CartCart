"""Persist typed refinement recompute plans.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recompute_plans",
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("refinement_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("prior_result_version_id", sa.String(length=36), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["refinement_id"],
            ["refinement_requests.refinement_id"],
            name=op.f("fk_recompute_plans_refinement_id_refinement_requests"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["shopping_runs.run_id"],
            name=op.f("fk_recompute_plans_run_id_shopping_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["prior_result_version_id"],
            ["result_versions.result_version_id"],
            name=op.f("fk_recompute_plans_prior_result_version_id_result_versions"),
        ),
        sa.PrimaryKeyConstraint("plan_id", name=op.f("pk_recompute_plans")),
        sa.UniqueConstraint(
            "refinement_id", name=op.f("uq_recompute_plans_refinement_id")
        ),
    )
    op.create_index("ix_recompute_plans_run_id", "recompute_plans", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_recompute_plans_run_id", table_name="recompute_plans")
    op.drop_table("recompute_plans")
