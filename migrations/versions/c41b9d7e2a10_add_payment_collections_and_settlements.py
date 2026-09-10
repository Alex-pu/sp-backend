"""add payment collections, shop payment codes, and settlements

Revision ID: c41b9d7e2a10
Revises: ad8b122f35f1
"""

from datetime import datetime
import uuid

from alembic import op
import sqlalchemy as sa


revision = 'c41b9d7e2a10'
down_revision = 'ad8b122f35f1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('shops', sa.Column('payment_code', sa.String(length=20), nullable=True))
    op.create_index('ix_shops_payment_code', 'shops', ['payment_code'], unique=True)

    bind = op.get_bind()
    shops = bind.execute(sa.text('select id from shops order by created_at, id')).all()
    for index, shop in enumerate(shops, start=1):
        bind.execute(
            sa.text('update shops set payment_code = :code where id = :id'),
            {'code': f'S{index:02d}', 'id': shop[0]},
        )

    op.create_table(
        'mpesa_payments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('shop_id', sa.String(length=36), nullable=True),
        sa.Column('transaction_id', sa.String(length=36), nullable=True),
        sa.Column('method', sa.String(length=30), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('account_reference', sa.String(length=100), nullable=True),
        sa.Column('phone_number', sa.String(length=30), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('provider_request_id', sa.String(length=100), nullable=True),
        sa.Column('provider_receipt_number', sa.String(length=100), nullable=True),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('raw_callback', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('matched_by', sa.String(length=36), nullable=True),
        sa.Column('matched_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id']),
        sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id']),
        sa.ForeignKeyConstraint(['matched_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider_request_id'),
        sa.UniqueConstraint('provider_receipt_number'),
    )
    op.create_index('ix_mpesa_payments_shop_id', 'mpesa_payments', ['shop_id'])
    op.create_index('ix_mpesa_payments_transaction_id', 'mpesa_payments', ['transaction_id'])
    op.create_index('ix_mpesa_payments_account_reference', 'mpesa_payments', ['account_reference'])
    op.create_index('ix_mpesa_payments_status', 'mpesa_payments', ['status'])
    op.create_index('ix_mpesa_payments_created_at', 'mpesa_payments', ['created_at'])

    op.create_table(
        'settlements',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('shop_id', sa.String(length=36), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('destination_type', sa.String(length=20), nullable=False),
        sa.Column('destination', sa.String(length=120), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('requested_by', sa.String(length=36), nullable=False),
        sa.Column('provider_reference', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id']),
        sa.ForeignKeyConstraint(['requested_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_settlements_shop_id', 'settlements', ['shop_id'])
    op.create_index('ix_settlements_status', 'settlements', ['status'])


def downgrade():
    op.drop_index('ix_settlements_status', table_name='settlements')
    op.drop_index('ix_settlements_shop_id', table_name='settlements')
    op.drop_table('settlements')
    op.drop_index('ix_mpesa_payments_created_at', table_name='mpesa_payments')
    op.drop_index('ix_mpesa_payments_status', table_name='mpesa_payments')
    op.drop_index('ix_mpesa_payments_account_reference', table_name='mpesa_payments')
    op.drop_index('ix_mpesa_payments_transaction_id', table_name='mpesa_payments')
    op.drop_index('ix_mpesa_payments_shop_id', table_name='mpesa_payments')
    op.drop_table('mpesa_payments')
    op.drop_index('ix_shops_payment_code', table_name='shops')
    op.drop_column('shops', 'payment_code')