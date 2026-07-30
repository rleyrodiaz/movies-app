"""add app_version_commits

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-30 00:17:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_version_commits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("commit_sha"),
    )


def downgrade() -> None:
    op.drop_table("app_version_commits")
