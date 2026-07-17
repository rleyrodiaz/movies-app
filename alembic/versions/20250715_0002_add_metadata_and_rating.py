"""add metadata and rating

Revision ID: 0002
Revises: 0001
Create Date: 2025-07-15 00:01:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("suggestions", sa.Column("genres", sa.Text(), nullable=True))
    op.add_column("suggestions", sa.Column("origin_country", sa.String(100), nullable=True))
    op.add_column("suggestions", sa.Column("cast_summary", sa.Text(), nullable=True))
    op.add_column("suggestions", sa.Column("providers", sa.Text(), nullable=True))
    op.add_column("suggestions", sa.Column("episode_count", sa.Integer(), nullable=True))
    op.add_column("watchlist_entries", sa.Column("rating", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("watchlist_entries", "rating")
    op.drop_column("suggestions", "episode_count")
    op.drop_column("suggestions", "providers")
    op.drop_column("suggestions", "cast_summary")
    op.drop_column("suggestions", "origin_country")
    op.drop_column("suggestions", "genres")
