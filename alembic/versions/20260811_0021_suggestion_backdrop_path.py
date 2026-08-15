"""add backdrop_path to suggestions

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-11 00:21:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("suggestions", sa.Column("backdrop_path", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("suggestions", "backdrop_path")
