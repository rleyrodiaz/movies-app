"""add clubs table and club_id columns

Revision ID: 0013
Revises: 0012
Create Date: 2025-07-23 00:13:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clubs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO clubs (name, created_at) VALUES ('Club Original', NOW())")

    op.add_column("users", sa.Column("club_id", sa.Integer(), nullable=True))
    op.add_column("suggestions", sa.Column("club_id", sa.Integer(), nullable=True))
    op.add_column("invitations", sa.Column("club_id", sa.Integer(), nullable=True))
    op.add_column("activity_log", sa.Column("club_id", sa.Integer(), nullable=True))

    op.execute("UPDATE users SET club_id = 1")
    op.execute("UPDATE suggestions SET club_id = 1")
    op.execute("UPDATE invitations SET club_id = 1")
    op.execute(
        """
        UPDATE activity_log a
        SET club_id = u.club_id
        FROM users u
        WHERE a.user_id = u.id
        """
    )

    op.alter_column("users", "club_id", nullable=False)
    op.alter_column("suggestions", "club_id", nullable=False)
    op.alter_column("invitations", "club_id", nullable=False)

    op.create_foreign_key("fk_users_club_id", "users", "clubs", ["club_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_suggestions_club_id", "suggestions", "clubs", ["club_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_invitations_club_id", "invitations", "clubs", ["club_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_activity_log_club_id", "activity_log", "clubs", ["club_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_activity_log_club_id", "activity_log", type_="foreignkey")
    op.drop_constraint("fk_invitations_club_id", "invitations", type_="foreignkey")
    op.drop_constraint("fk_suggestions_club_id", "suggestions", type_="foreignkey")
    op.drop_constraint("fk_users_club_id", "users", type_="foreignkey")

    op.drop_column("activity_log", "club_id")
    op.drop_column("invitations", "club_id")
    op.drop_column("suggestions", "club_id")
    op.drop_column("users", "club_id")

    op.drop_table("clubs")
