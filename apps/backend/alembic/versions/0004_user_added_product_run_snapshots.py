"""Keep the considered-product outcome of each completed run.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_added_product_run_snapshots",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("user_added", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["shopping_runs.run_id"],
            name=op.f("fk_user_added_product_run_snapshots_run_id_shopping_runs"),
        ),
        sa.PrimaryKeyConstraint(
            "run_id",
            "candidate_id",
            name=op.f("pk_user_added_product_run_snapshots"),
        ),
    )
    op.create_index(
        "ix_user_added_product_run_snapshots_run_id",
        "user_added_product_run_snapshots",
        ["run_id"],
    )
    op.execute(
        "INSERT INTO user_added_product_run_snapshots (run_id, candidate_id, user_added) "
        "SELECT run_id, candidate_id, user_added FROM user_added_products "
        "WHERE run_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_added_product_run_snapshots_run_id",
        table_name="user_added_product_run_snapshots",
    )
    op.drop_table("user_added_product_run_snapshots")
