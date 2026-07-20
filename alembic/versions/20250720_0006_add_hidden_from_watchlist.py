"""add hidden_from_watchlist to watchlist_entries

Revision ID: 0006
Revises: 0005
Create Date: 2025-07-20 00:06:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "watchlist_entries",
        sa.Column("hidden_from_watchlist", sa.Boolean(), nullable=False, server_default="false"),
    )
    # Backfill: las entradas del propio sugeridor son las que el flujo de
    # "Nueva sugerencia" creaba automáticamente; se ocultan de "Mi watchlist"
    # para igualar el comportamiento nuevo con los datos existentes.
    op.execute(
        """
        UPDATE watchlist_entries we
        SET hidden_from_watchlist = true
        FROM suggestions s
        WHERE we.suggestion_id = s.id
          AND we.user_id = s.suggested_by
        """
    )


def downgrade() -> None:
    op.drop_column("watchlist_entries", "hidden_from_watchlist")
