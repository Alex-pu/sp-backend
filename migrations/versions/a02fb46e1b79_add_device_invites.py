"""add device invites

Revision ID: a02fb46e1b79
Revises: e239e203d230
Create Date: 2026-08-13 13:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'a02fb46e1b79'
down_revision = 'e239e203d230'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'device_invites',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('shop_id', sa.String(length=36), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('created_by', sa.String(length=36), nullable=False),
        sa.Column('device_label', sa.String(length=120), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('accepted_at', sa.DateTime(), nullable=True),
        sa.Column('accepted_device_id', sa.String(length=120), nullable=True),
        sa.Column('accepted_device_label', sa.String(length=120), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_device_invites_expires_at'), 'device_invites', ['expires_at'], unique=False)
    op.create_index(op.f('ix_device_invites_shop_id'), 'device_invites', ['shop_id'], unique=False)
    op.create_index(op.f('ix_device_invites_status'), 'device_invites', ['status'], unique=False)
    op.create_index(op.f('ix_device_invites_token_hash'), 'device_invites', ['token_hash'], unique=True)


def downgrade():
    op.drop_index(op.f('ix_device_invites_token_hash'), table_name='device_invites')
    op.drop_index(op.f('ix_device_invites_status'), table_name='device_invites')
    op.drop_index(op.f('ix_device_invites_shop_id'), table_name='device_invites')
    op.drop_index(op.f('ix_device_invites_expires_at'), table_name='device_invites')
    op.drop_table('device_invites')
