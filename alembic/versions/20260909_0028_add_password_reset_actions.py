"""add password_reset_requested/password_reset_completed activityaction enum values

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-09 00:28:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE activityaction ADD VALUE IF NOT EXISTS 'password_reset_requested'")
    op.execute("ALTER TYPE activityaction ADD VALUE IF NOT EXISTS 'password_reset_completed'")


def downgrade() -> None:
    # Postgres no permite quitar valores de un enum de forma directa; no-op.
    pass
