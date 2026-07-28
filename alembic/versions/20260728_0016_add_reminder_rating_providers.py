"""add tmdb_rating and providers to personal_reminders

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-28 00:16:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("personal_reminders", sa.Column("tmdb_rating", sa.Float(), nullable=True))
    op.add_column("personal_reminders", sa.Column("providers", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("personal_reminders", "providers")
    op.drop_column("personal_reminders", "tmdb_rating")
