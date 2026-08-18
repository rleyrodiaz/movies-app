"""add created_in_club_id to personal_reminders (informational only)

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-17 00:22:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "personal_reminders",
        sa.Column("created_in_club_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_personal_reminders_created_in_club_id",
        "personal_reminders", "clubs",
        ["created_in_club_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_personal_reminders_created_in_club_id", "personal_reminders", type_="foreignkey")
    op.drop_column("personal_reminders", "created_in_club_id")
