"""add cadence_profile column to campaigns and cadence_campaigns (Task #220)

Revision ID: d72f5e0c4a18
Revises: c4e21d8f0a13
Create Date: 2026-05-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd72f5e0c4a18'
down_revision: Union[str, None] = 'c4e21d8f0a13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE campaigns
            ADD COLUMN IF NOT EXISTS cadence_profile VARCHAR(20) NOT NULL DEFAULT 'conservador';
    """)
    op.execute("""
        ALTER TABLE cadence_campaigns
            ADD COLUMN IF NOT EXISTS cadence_profile VARCHAR(20) NOT NULL DEFAULT 'conservador';
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE campaigns
            DROP COLUMN IF EXISTS cadence_profile;
    """)
    op.execute("""
        ALTER TABLE cadence_campaigns
            DROP COLUMN IF EXISTS cadence_profile;
    """)
