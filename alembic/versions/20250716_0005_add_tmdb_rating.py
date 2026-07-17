"""add tmdb_rating to suggestions

Revision ID: 0005
Revises: 0004
Create Date: 2025-07-16 00:05:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("suggestions", sa.Column("tmdb_rating", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("suggestions", "tmdb_rating")
