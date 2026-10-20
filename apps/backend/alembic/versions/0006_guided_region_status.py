from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shopping_sessions",
        sa.Column("guided_region_status", sa.String(length=16), nullable=True),
    )
    op.add_column("shopping_sessions", sa.Column("guided_answers", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("shopping_sessions", "guided_answers")
    op.drop_column("shopping_sessions", "guided_region_status")
