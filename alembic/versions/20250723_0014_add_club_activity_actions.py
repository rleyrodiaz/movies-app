"""add club-related activityaction enum values

Revision ID: 0014
Revises: 0013
Create Date: 2025-07-23 00:14:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_VALUES = [
    "club_created",
    "club_renamed",
    "club_switched",
]


def upgrade() -> None:
    for value in NEW_VALUES:
        op.execute(f"ALTER TYPE activityaction ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres no permite quitar valores de un enum de forma directa; no-op.
    pass
