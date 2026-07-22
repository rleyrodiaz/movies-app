"""add new activityaction enum values

Revision ID: 0012
Revises: 0011
Create Date: 2025-07-22 00:12:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_VALUES = [
    "suggestion_deleted",
    "watchlist_added",
    "watchlist_removed",
    "watchlist_rated",
    "reminder_created",
]


def upgrade() -> None:
    for value in NEW_VALUES:
        op.execute(f"ALTER TYPE activityaction ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres no permite quitar valores de un enum de forma directa; no-op.
    pass
