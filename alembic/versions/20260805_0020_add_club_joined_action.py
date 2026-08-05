"""add club_joined activityaction enum value

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-05 00:20:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE activityaction ADD VALUE IF NOT EXISTS 'club_joined'")


def downgrade() -> None:
    # Postgres no permite quitar valores de un enum de forma directa; no-op.
    pass
