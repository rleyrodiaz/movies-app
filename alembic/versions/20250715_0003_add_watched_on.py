"""add watched_on to watchlist_entries

Revision ID: 0003
Revises: 0002
Create Date: 2025-07-15 00:02:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("watchlist_entries", sa.Column("watched_on", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("watchlist_entries", "watched_on")
