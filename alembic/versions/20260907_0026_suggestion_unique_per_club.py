"""add unique constraint on suggestions (tmdb_id, media_type, club_id)

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-07 00:26:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_suggestion_tmdb_media_club",
        "suggestions",
        ["tmdb_id", "media_type", "club_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_suggestion_tmdb_media_club", "suggestions", type_="unique")
