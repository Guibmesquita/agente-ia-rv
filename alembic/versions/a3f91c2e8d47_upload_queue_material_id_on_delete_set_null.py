"""upload_queue_material_id_on_delete_set_null

Revision ID: a3f91c2e8d47
Revises: 1dca74983b6b
Create Date: 2026-04-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3f91c2e8d47'
down_revision: Union[str, None] = '1dca74983b6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE upload_queue_items
            DROP CONSTRAINT IF EXISTS upload_queue_items_material_id_fkey;
    """)
    op.execute("""
        ALTER TABLE upload_queue_items
            ALTER COLUMN material_id DROP NOT NULL;
    """)
    op.execute("""
        ALTER TABLE upload_queue_items
            ADD CONSTRAINT upload_queue_items_material_id_fkey
            FOREIGN KEY (material_id)
            REFERENCES materials(id)
            ON DELETE SET NULL;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE upload_queue_items
            DROP CONSTRAINT IF EXISTS upload_queue_items_material_id_fkey;
    """)
    # Rows with material_id IS NULL were produced by ON DELETE SET NULL —
    # their referenced material no longer exists. Deleting them is the only
    # safe way to restore NOT NULL without referencing a phantom placeholder.
    op.execute("""
        DELETE FROM upload_queue_items WHERE material_id IS NULL;
    """)
    op.execute("""
        ALTER TABLE upload_queue_items
            ALTER COLUMN material_id SET NOT NULL;
    """)
    op.execute("""
        ALTER TABLE upload_queue_items
            ADD CONSTRAINT upload_queue_items_material_id_fkey
            FOREIGN KEY (material_id)
            REFERENCES materials(id);
    """)
