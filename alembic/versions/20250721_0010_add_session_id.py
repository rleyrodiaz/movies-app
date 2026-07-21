"""add session_id to activity_log

Revision ID: 0010
Revises: 0009
Create Date: 2025-07-21 00:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("activity_log", sa.Column("session_id", sa.String(32), nullable=True))
    op.create_index("ix_activity_log_session_id", "activity_log", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_activity_log_session_id", table_name="activity_log")
    op.drop_column("activity_log", "session_id")
