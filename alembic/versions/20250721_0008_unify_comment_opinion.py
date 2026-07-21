"""unify opinion and comments into watchlist_entries.comment

Revision ID: 0008
Revises: 0007
Create Date: 2025-07-21 00:08:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("watchlist_entries", "opinion", new_column_name="comment")

    # Backfill: el comentario más antiguo de cada usuario en cada sugerencia
    # (típicamente el que dejó al sugerirla) pasa a ser su comentario unificado,
    # si esa entrada de watchlist todavía no tiene uno.
    op.execute(
        """
        UPDATE watchlist_entries we
        SET comment = c.body
        FROM (
            SELECT DISTINCT ON (suggestion_id, user_id) suggestion_id, user_id, body
            FROM comments
            ORDER BY suggestion_id, user_id, created_at ASC
        ) c
        WHERE we.suggestion_id = c.suggestion_id
          AND we.user_id = c.user_id
          AND we.comment IS NULL
        """
    )

    op.drop_table("comments")


def downgrade() -> None:
    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("suggestion_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["suggestion_id"], ["suggestions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.alter_column("watchlist_entries", "comment", new_column_name="opinion")
