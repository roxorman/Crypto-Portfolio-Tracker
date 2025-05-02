"""Make chain optional in portfolio_wallets

Revision ID: 7d447c843107
Revises: ea62a4ccea69
Create Date: 2025-05-02 14:32:52.041412

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d447c843107'
down_revision: Union[str, None] = 'ea62a4ccea69'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ### adjusted Alembic commands ###
    # 1. Drop the old primary key constraint (assuming default name)
    op.drop_constraint('portfolio_wallets_pkey', 'portfolio_wallets', type_='primary')

    # 2. Add the new association_id column and make it the primary key
    # Note: Autoincrement is usually handled by default for Integer PKs in PostgreSQL
    op.add_column('portfolio_wallets', sa.Column('association_id', sa.Integer(), nullable=False, primary_key=True))

    # 3. Make the chain column nullable
    op.alter_column('portfolio_wallets', 'chain',
               existing_type=sa.VARCHAR(length=50),
               nullable=True)

    # 4. Create the unique constraint and index
    op.create_unique_constraint('uq_portfolio_wallet_chain', 'portfolio_wallets', ['portfolio_id', 'wallet_id', 'chain'])
    op.create_index('idx_portfolio_wallets_chain', 'portfolio_wallets', ['chain'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### adjusted Alembic commands ###
    # 1. Drop the unique constraint and index
    op.drop_constraint('uq_portfolio_wallet_chain', 'portfolio_wallets', type_='unique')
    op.drop_index('idx_portfolio_wallets_chain', table_name='portfolio_wallets')

    # 2. Make the chain column non-nullable again
    op.alter_column('portfolio_wallets', 'chain',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)

    # 3. Drop the association_id column (implicitly drops the new PK)
    op.drop_column('portfolio_wallets', 'association_id')

    # 4. Recreate the original primary key constraint
    op.create_primary_key(
        'portfolio_wallets_pkey', 'portfolio_wallets',
        ['portfolio_id', 'wallet_id', 'chain']
    )
    # ### end Alembic commands ###
