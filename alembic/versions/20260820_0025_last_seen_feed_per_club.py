"""move last_seen_feed_at from users to club_memberships (per-club, not global)

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-20 00:25:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("club_memberships", sa.Column("last_seen_feed_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_column("users", "last_seen_feed_at")


def downgrade() -> None:
    op.add_column("users", sa.Column("last_seen_feed_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_column("club_memberships", "last_seen_feed_at")
