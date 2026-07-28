"""add platforms to users

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-27 00:15:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("platforms", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "platforms")
