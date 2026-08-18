"""add runtime_minutes to suggestions

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-18 00:23:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("suggestions", sa.Column("runtime_minutes", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("suggestions", "runtime_minutes")
