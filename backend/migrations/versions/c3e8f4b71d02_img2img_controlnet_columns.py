"""img2img + controlnet columns on image_jobs

Revision ID: c3e8f4b71d02
Revises: a1274da2193a
Create Date: 2026-07-01 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c3e8f4b71d02'
down_revision: Union[str, None] = 'a1274da2193a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('image_jobs', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('mode', sa.String(length=16), nullable=False, server_default='txt2img')
        )
        batch_op.add_column(sa.Column('strength', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('controlnet_type', sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column('init_image_path', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('control_image_path', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('image_jobs', schema=None) as batch_op:
        batch_op.drop_column('control_image_path')
        batch_op.drop_column('init_image_path')
        batch_op.drop_column('controlnet_type')
        batch_op.drop_column('strength')
        batch_op.drop_column('mode')
