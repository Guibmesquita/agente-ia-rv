"""add_outbox_messages_table

Revision ID: 1dca74983b6b
Revises: 
Create Date: 2026-03-20 13:22:10.939009

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '1dca74983b6b'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS outbox_messages (
            id SERIAL PRIMARY KEY,
            dedupe_key VARCHAR(255) NOT NULL UNIQUE,
            phone VARCHAR(50) NOT NULL,
            message_type VARCHAR(20) NOT NULL,
            status VARCHAR(10) NOT NULL DEFAULT 'PENDING',
            zaap_id VARCHAR(255),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            sent_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_outbox_messages_dedupe_key ON outbox_messages(dedupe_key)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS outbox_messages CASCADE")
