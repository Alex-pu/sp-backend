"""add user contact details

Revision ID: ad8b122f35f1
Revises: e239e203d230
Create Date: 2026-08-14 12:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ad8b122f35f1'
down_revision = 'e239e203d230'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('phone', sa.String(length=30), nullable=True))
        batch_op.create_unique_constraint('uq_users_email', ['email'])


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('uq_users_email', type_='unique')
        batch_op.drop_column('phone')
        batch_op.drop_column('email')
