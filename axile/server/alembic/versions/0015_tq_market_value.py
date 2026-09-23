"""Repair historical TQ cost-basis market values."""

from alembic import op

from axile.server.migration_support.tq_market_value import downgrade as restore
from axile.server.migration_support.tq_market_value import upgrade as repair

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Repair TQ observations."""
    repair(op.get_bind())


def downgrade() -> None:
    """Restore guarded original JSON."""
    restore(op.get_bind())
