"""Repair historical CTP cost-basis market values from execution tick evidence."""

from alembic import op

from axile.server.migration_support.ctp_market_value import downgrade as restore
from axile.server.migration_support.ctp_market_value import upgrade as repair

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Repair joined CTP asset observations with audit provenance."""
    repair(op.get_bind())


def downgrade() -> None:
    """Restore guarded original JSON values."""
    restore(op.get_bind())
