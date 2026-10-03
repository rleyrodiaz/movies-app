"""add announcement_draft to clubs

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-03 00:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clubs", sa.Column("announcement_draft", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("clubs", "announcement_draft")
