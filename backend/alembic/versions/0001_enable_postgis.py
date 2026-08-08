"""Enable the PostGIS extension.

Kept as its own revision, ahead of any table creation, because every
geometry column in the schema depends on it.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")


def downgrade() -> None:
    # Not dropped: other databases in the cluster, or manually created
    # geometry columns, may still depend on it.
    pass
