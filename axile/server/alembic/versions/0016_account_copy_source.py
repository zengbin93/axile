"""Store the source account snapshot for copied accounts."""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add source fields without a foreign key so deletion preserves provenance."""
    op.add_column("account", sa.Column("copied_from_account_id", sa.Integer(), nullable=True))
    op.add_column("account", sa.Column("copied_from_account_name", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove source fields."""
    op.drop_column("account", "copied_from_account_name")
    op.drop_column("account", "copied_from_account_id")
