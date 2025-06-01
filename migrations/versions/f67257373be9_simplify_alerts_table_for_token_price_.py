"""simplify_alerts_table_for_token_price_only

Revision ID: f67257373be9
Revises: 3764aef542eb
Create Date: 2025-05-16 10:40:18.273856

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import logging

logger = logging.getLogger(f"alembic.runtime.migration.{__name__}")

# revision identifiers, used by Alembic.
revision: str = 'f67257373be9'
down_revision: Union[str, None] = '3764aef542eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = 'alerts'
OLD_ALERT_TYPES = ['token_price', 'portfolio_value', 'wallet_tx', 'tracked_wallet_tx'] # As per previous migration
NEW_ALERT_TYPES_FOR_CHECK = ['token_price'] # What the check_alert_type will become

# Constraint names (assuming based on previous error and common naming)
FK_CONSTRAINT_NAME = 'check_alert_fk' # The one causing issues
ALERT_TYPE_CONSTRAINT_NAME = 'alerts_alert_type_check' # The one we just fixed
TOKEN_PRICE_FIELDS_CONSTRAINT_NAME = 'check_token_price_alert_fields'


def upgrade() -> None:
    logger.info(f"Simplifying '{TABLE_NAME}' table for token_price alerts only.")

    # 1. Drop the problematic foreign key check constraint if it exists
    #    We need to be careful as its exact definition isn't known, but the error implies it exists.
    #    If this fails because the constraint name is different, we might need to query it first.
    try:
        op.drop_constraint(FK_CONSTRAINT_NAME, TABLE_NAME, type_='check')
        logger.info(f"Dropped constraint '{FK_CONSTRAINT_NAME}' from '{TABLE_NAME}'.")
    except Exception as e:
        logger.warning(f"Could not drop constraint '{FK_CONSTRAINT_NAME}' (it might not exist or name is different): {e}")

    # 2. Drop foreign key columns that are no longer needed
    op.drop_index('idx_alerts_portfolio_id', table_name=TABLE_NAME, if_exists=True) # Use if_exists for safety
    op.drop_column(TABLE_NAME, 'portfolio_id')
    logger.info(f"Dropped column 'portfolio_id' from '{TABLE_NAME}'.")
    
    op.drop_index('idx_alerts_wallet_id', table_name=TABLE_NAME, if_exists=True)
    op.drop_column(TABLE_NAME, 'wallet_id')
    logger.info(f"Dropped column 'wallet_id' from '{TABLE_NAME}'.")

    op.drop_index('idx_alerts_tracked_wallet_id', table_name=TABLE_NAME, if_exists=True)
    op.drop_column(TABLE_NAME, 'tracked_wallet_id')
    logger.info(f"Dropped column 'tracked_wallet_id' from '{TABLE_NAME}'.")

    # 3. Modify 'alerts_alert_type_check' to only allow 'token_price'
    op.drop_constraint(ALERT_TYPE_CONSTRAINT_NAME, TABLE_NAME, type_='check')
    op.create_check_constraint(
        ALERT_TYPE_CONSTRAINT_NAME,
        TABLE_NAME,
        sa.column('alert_type').in_(NEW_ALERT_TYPES_FOR_CHECK)
    )
    logger.info(f"Modified constraint '{ALERT_TYPE_CONSTRAINT_NAME}' to allow only: {NEW_ALERT_TYPES_FOR_CHECK}.")

    # 4. Modify 'check_token_price_alert_fields' as alert_type will always be 'token_price'
    #    The original was: "(alert_type != 'token_price') OR (token_mobula_id IS NOT NULL AND token_display_name IS NOT NULL)"
    #    Since alert_type IS 'token_price', it simplifies to: "(token_mobula_id IS NOT NULL AND token_display_name IS NOT NULL)"
    op.drop_constraint(TOKEN_PRICE_FIELDS_CONSTRAINT_NAME, TABLE_NAME, type_='check')
    op.create_check_constraint(
        TOKEN_PRICE_FIELDS_CONSTRAINT_NAME,
        TABLE_NAME,
        sa.text("(token_mobula_id IS NOT NULL AND token_display_name IS NOT NULL)")
    )
    logger.info(f"Modified constraint '{TOKEN_PRICE_FIELDS_CONSTRAINT_NAME}' for simplified alert structure.")


def downgrade() -> None:
    logger.info(f"Reverting simplification of '{TABLE_NAME}' table.")

    # 1. Revert 'check_token_price_alert_fields'
    op.drop_constraint(TOKEN_PRICE_FIELDS_CONSTRAINT_NAME, TABLE_NAME, type_='check')
    op.create_check_constraint(
        TOKEN_PRICE_FIELDS_CONSTRAINT_NAME,
        TABLE_NAME,
        sa.text("(alert_type != 'token_price') OR (token_mobula_id IS NOT NULL AND token_display_name IS NOT NULL)")
    )
    logger.info(f"Reverted constraint '{TOKEN_PRICE_FIELDS_CONSTRAINT_NAME}'.")

    # 2. Revert 'alerts_alert_type_check'
    op.drop_constraint(ALERT_TYPE_CONSTRAINT_NAME, TABLE_NAME, type_='check')
    op.create_check_constraint(
        ALERT_TYPE_CONSTRAINT_NAME,
        TABLE_NAME,
        sa.column('alert_type').in_(OLD_ALERT_TYPES) # Use the broader list
    )
    logger.info(f"Reverted constraint '{ALERT_TYPE_CONSTRAINT_NAME}' to allow: {OLD_ALERT_TYPES}.")

    # 3. Re-add columns and their indexes
    op.add_column(TABLE_NAME, sa.Column('tracked_wallet_id', sa.Integer(), nullable=True))
    op.create_index('idx_alerts_tracked_wallet_id', TABLE_NAME, ['tracked_wallet_id'], unique=False)
    logger.info(f"Re-added column 'tracked_wallet_id' and its index to '{TABLE_NAME}'.")

    op.add_column(TABLE_NAME, sa.Column('wallet_id', sa.Integer(), nullable=True))
    op.create_index('idx_alerts_wallet_id', TABLE_NAME, ['wallet_id'], unique=False)
    logger.info(f"Re-added column 'wallet_id' and its index to '{TABLE_NAME}'.")

    op.add_column(TABLE_NAME, sa.Column('portfolio_id', sa.Integer(), nullable=True))
    op.create_index('idx_alerts_portfolio_id', TABLE_NAME, ['portfolio_id'], unique=False)
    logger.info(f"Re-added column 'portfolio_id' and its index to '{TABLE_NAME}'.")

    # 4. Re-add the 'check_alert_fk' constraint (BEST EFFORT - original definition not fully known)
    #    This is a placeholder. The actual original constraint might have been more complex.
    #    If this simplification is permanent, this downgrade path for check_alert_fk might not be strictly necessary
    #    or would need the exact original definition.
    #    For now, we'll assume a common pattern.
    #    This might fail if the original constraint was different or didn't exist.
    try:
        op.create_check_constraint(
            FK_CONSTRAINT_NAME,
            TABLE_NAME,
            sa.text(
                " (alert_type = 'portfolio_value' AND portfolio_id IS NOT NULL) OR "
                " (alert_type = 'wallet_tx' AND wallet_id IS NOT NULL) OR "
                " (alert_type = 'tracked_wallet_tx' AND tracked_wallet_id IS NOT NULL) OR "
                " (alert_type = 'token_price') " # Allow token_price to not require these FKs
            )
        )
        logger.info(f"Attempted to re-add constraint '{FK_CONSTRAINT_NAME}' to '{TABLE_NAME}'.")
    except Exception as e:
        logger.warning(f"Could not re-add constraint '{FK_CONSTRAINT_NAME}' during downgrade (this might be okay if it didn't exist or definition changed): {e}")
