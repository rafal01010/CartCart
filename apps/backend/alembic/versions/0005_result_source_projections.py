"""Freeze source and candidate projections for new result versions.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "result_source_projections",
        sa.Column("result_version_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["result_version_id"], ["result_versions.result_version_id"],
            name=op.f("fk_result_source_projections_result_version_id_result_versions"),
        ),
        sa.PrimaryKeyConstraint("result_version_id", name=op.f("pk_result_source_projections")),
    )


def downgrade() -> None:
    op.drop_table("result_source_projections")
