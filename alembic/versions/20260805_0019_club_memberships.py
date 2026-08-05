"""club_memberships table: users can belong to more than one club

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-05 00:19:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    userrole = postgresql.ENUM("user", "admin", "superadmin", name="userrole", create_type=False)
    op.create_table(
        "club_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("club_id", sa.Integer(), sa.ForeignKey("clubs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", userrole, nullable=False, server_default="user"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "club_id", name="uq_club_membership_user_club"),
    )

    # Backfill: cada usuario existente se vuelve miembro de su club actual, con su
    # rol actual (los superadmin quedan "admin" en su propia membresía — su poder
    # global no depende de esto, ver users.is_superadmin más abajo).
    op.execute("""
        INSERT INTO club_memberships (user_id, club_id, role, created_at)
        SELECT id, club_id, CASE WHEN role = 'superadmin' THEN 'admin' ELSE role END, NOW()
        FROM users
    """)

    op.add_column("users", sa.Column("is_superadmin", sa.Boolean(), nullable=False, server_default="false"))
    op.execute("UPDATE users SET is_superadmin = true WHERE role = 'superadmin'")

    op.add_column("users", sa.Column("last_active_club_id", sa.Integer(), sa.ForeignKey("clubs.id", ondelete="SET NULL"), nullable=True))
    op.execute("UPDATE users SET last_active_club_id = club_id")

    op.drop_column("users", "club_id")
    op.drop_column("users", "role")


def downgrade() -> None:
    userrole = postgresql.ENUM("user", "admin", "superadmin", name="userrole", create_type=False)
    op.add_column("users", sa.Column("club_id", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("role", userrole, nullable=False, server_default="user"))

    op.execute("""
        UPDATE users u
        SET club_id = m.club_id, role = m.role
        FROM (
            SELECT DISTINCT ON (user_id) user_id, club_id, role
            FROM club_memberships
            ORDER BY user_id, id
        ) m
        WHERE u.id = m.user_id
    """)
    op.execute("UPDATE users SET role = 'superadmin' WHERE is_superadmin = true")

    op.alter_column("users", "club_id", nullable=False)
    op.create_foreign_key("users_club_id_fkey", "users", "clubs", ["club_id"], ["id"], ondelete="CASCADE")

    op.drop_column("users", "last_active_club_id")
    op.drop_column("users", "is_superadmin")
    op.drop_table("club_memberships")
