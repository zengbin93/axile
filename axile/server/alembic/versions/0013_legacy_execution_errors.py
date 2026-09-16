"""Repair deterministic public legacy execution error explanations."""

from alembic import op

from axile.server.migration_support.v1 import PUBLIC_CODES, apply, restore

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Write readable public-channel explanations without changing execution state."""
    apply(op.get_bind(), "axile_0013_error_backup", PUBLIC_CODES)


def downgrade() -> None:
    """Restore only fields written by this revision, rejecting concurrent edits."""
    restore(op.get_bind(), "axile_0013_error_backup")
