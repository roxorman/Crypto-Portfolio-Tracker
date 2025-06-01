"""update_alert_type_check_constraint

Revision ID: 3764aef542eb
Revises: e97bbf94c241
Create Date: 2025-05-16 10:07:51.751617

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3764aef542eb'
down_revision: Union[str, None] = 'e97bbf94c241'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Define the constraint name based on the error message
CONSTRAINT_NAME = 'alerts_alert_type_check' 
# Define the table name
TABLE_NAME = 'alerts'
# Define the column name
COLUMN_NAME = 'alert_type'

# Define the new valid alert types
NEW_ALERT_TYPES = ['token_price', 'portfolio_value', 'wallet_tx', 'tracked_wallet_tx']
# Define the old valid alert types (before adding 'token_price')
OLD_ALERT_TYPES = ['portfolio_value', 'wallet_tx', 'tracked_wallet_tx']


def upgrade() -> None:
    """Upgrade schema to include 'token_price' in alert_type check constraint."""
    # Drop the existing constraint
    op.drop_constraint(CONSTRAINT_NAME, TABLE_NAME, type_='check')
    
    # Create the new constraint with updated alert types
    op.create_check_constraint(
        CONSTRAINT_NAME,
        TABLE_NAME,
        sa.column(COLUMN_NAME).in_(NEW_ALERT_TYPES)
    )
    logger.info(f"Upgraded constraint '{CONSTRAINT_NAME}' on table '{TABLE_NAME}' to allow types: {NEW_ALERT_TYPES}")


def downgrade() -> None:
    """Downgrade schema to revert 'token_price' from alert_type check constraint."""
    # Drop the new constraint
    op.drop_constraint(CONSTRAINT_NAME, TABLE_NAME, type_='check')
    
    # Recreate the old constraint with previous alert types
    op.create_check_constraint(
        CONSTRAINT_NAME,
        TABLE_NAME,
        sa.column(COLUMN_NAME).in_(OLD_ALERT_TYPES)
    )
    logger.info(f"Downgraded constraint '{CONSTRAINT_NAME}' on table '{TABLE_NAME}' to allow types: {OLD_ALERT_TYPES}")

# Add logger import for the log messages in upgrade/downgrade
import logging
logger = logging.getLogger(f"alembic.runtime.migration.{__name__}")
