"""add portfolios.aliases column (Task #213)

Revision ID: c4e21d8f0a13
Revises: a3f91c2e8d47
Create Date: 2026-05-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c4e21d8f0a13'
down_revision: Union[str, None] = 'a3f91c2e8d47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE portfolios
            ADD COLUMN IF NOT EXISTS aliases TEXT DEFAULT '[]';
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE portfolios
            DROP COLUMN IF EXISTS aliases;
    """)
