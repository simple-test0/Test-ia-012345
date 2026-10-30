"""img2img columns on image_jobs

Revision ID: b7c3e1d2f4a5
Revises: a1274da2193a
Create Date: 2026-10-30 09:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c3e1d2f4a5'
down_revision: Union[str, None] = 'a1274da2193a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('image_jobs', sa.Column('init_image_path', sa.Text(), nullable=True))
    op.add_column('image_jobs', sa.Column('strength', sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('image_jobs') as batch:
        batch.drop_column('strength')
        batch.drop_column('init_image_path')
