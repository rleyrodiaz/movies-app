"""add season_count to suggestions

Revision ID: 0004
Revises: 0003
Create Date: 2025-07-16 00:04:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("suggestions", sa.Column("season_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("suggestions", "season_count")
