"""add created_at to watchlist_entries and convert watched_on to a real date

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-04 00:18:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "watchlist_entries",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.alter_column(
        "watchlist_entries",
        "watched_on",
        existing_type=sa.String(length=100),
        type_=sa.Date(),
        postgresql_using="watched_on::date",
    )


def downgrade() -> None:
    op.alter_column(
        "watchlist_entries",
        "watched_on",
        existing_type=sa.Date(),
        type_=sa.String(length=100),
    )
    op.drop_column("watchlist_entries", "created_at")
