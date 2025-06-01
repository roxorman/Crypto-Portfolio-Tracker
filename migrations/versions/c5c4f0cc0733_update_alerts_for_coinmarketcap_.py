"""update_alerts_for_coinmarketcap_integration

Revision ID: c5c4f0cc0733
Revises: f67257373be9
Create Date: 2025-05-16 20:45:25.127495

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import logging

logger = logging.getLogger(f"alembic.runtime.migration.{__name__}")

# revision identifiers, used by Alembic.
revision: str = 'c5c4f0cc0733'
down_revision: Union[str, None] = 'f67257373be9' # Previous migration that simplified alerts table
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = 'alerts'
OLD_TOKEN_PRICE_FIELDS_CONSTRAINT_NAME = 'check_token_price_alert_fields' # As defined in models.py before this change
# The new name will be the same, but the condition changes.

def upgrade() -> None:
    logger.info(f"Updating '{TABLE_NAME}' table for CoinMarketCap integration.")

    # 1. Add cmc_id column (Integer, nullable=False after data backfill if any, for now nullable=True then alter)
    #    Making it nullable=True initially to avoid issues if table has data, then alter.
    #    However, since we are dropping mobula_id, we should ensure new alerts have cmc_id.
    #    For a clean switch, if existing alerts are purely Mobula based and cannot be mapped,
    #    this migration might need to handle or delete them.
    #    Given the plan is to drop mobula_id, new alerts *must* have cmc_id.
    #    So, we add it as nullable=False if the table is expected to be empty of 'token_price' alerts
    #    or if we handle data migration. For now, let's assume we can add as nullable=False.
    
    # Step 1: Add cmc_id as nullable=True initially
    op.add_column(TABLE_NAME, sa.Column('cmc_id', sa.Integer(), nullable=True))
    logger.info(f"Added column 'cmc_id' (nullable) to '{TABLE_NAME}'.")

    # Step 2: Ensure token_display_name is nullable=True if it wasn't (it was from e97bbf94c241)
    # This is more of a safeguard if its previous state was non-nullable.
    # The migration e97bbf94c241 added it as nullable=True, so this alter might be redundant
    # but safe. If it's already nullable=True, this does nothing.
    op.alter_column(TABLE_NAME, 'token_display_name', existing_type=sa.String(length=255), nullable=True)
    logger.info(f"Ensured 'token_display_name' is nullable in '{TABLE_NAME}' before data operations.")

    # Step 3: Delete existing 'token_price' alerts as they are based on mobula_id which is being removed.
    # Users will need to recreate these alerts.
    op.execute("DELETE FROM alerts WHERE alert_type = 'token_price'")
    logger.info(f"Deleted existing 'token_price' alerts from '{TABLE_NAME}' to accommodate schema change.")

    # Step 4: Now alter cmc_id and token_display_name to be nullable=False
    op.alter_column(TABLE_NAME, 'cmc_id', existing_type=sa.Integer(), nullable=False)
    logger.info(f"Altered column 'cmc_id' in '{TABLE_NAME}' to non-nullable.")
    
    op.alter_column(TABLE_NAME, 'token_display_name', existing_type=sa.String(length=255), nullable=False) # This was step 5 in original plan
    logger.info(f"Altered column 'token_display_name' in '{TABLE_NAME}' to be non-nullable.")

    # Step 5 (was 2): Create index on cmc_id
    op.create_index('idx_alerts_cmc_id', TABLE_NAME, ['cmc_id'], unique=False)
    logger.info(f"Created index 'idx_alerts_cmc_id' on '{TABLE_NAME}'.")

    # 3. Create the new composite index for active CMC alerts
    op.create_index('idx_alerts_active_cmc_id', TABLE_NAME, ['is_active', 'cmc_id'], unique=False, postgresql_where=sa.text("alert_type = 'token_price'"))
    logger.info(f"Created index 'idx_alerts_active_cmc_id' on '{TABLE_NAME}'.")
    
    # 4. Drop the old token_mobula_id column and its specific index
    #    The index 'idx_alerts_active_token_mobula_id' was created in models.py but might not have a migration if added directly.
    #    Let's try to drop it using op.f() if it was auto-named, or its explicit name.
    #    The model had: Index('idx_alerts_active_token_mobula_id', 'is_active', 'token_mobula_id', postgresql_where=(alert_type == 'token_price'))
    #    And also: token_mobula_id = Column(BigInteger, nullable=True, index=True) which implies an index like 'ix_alerts_token_mobula_id'
    
    # Drop the composite index first if it exists by its explicit name from model
    # Adding if_exists=True if supported by the dialect, otherwise, the try-except is a fallback.
    # For PostgreSQL, direct drop with non-existence raises error.
    # A raw SQL "DROP INDEX IF EXISTS" might be more robust if op.drop_index doesn't handle this well.
    # However, let's try to make the try-except more specific or ensure the transaction isn't broken.
    # Given the error, the transaction is aborted. We need to ensure these drops don't cause that.
    # A better way for Alembic is to check for existence using inspector.

    conn = op.get_bind()
    inspector = sa.inspect(conn)
    indexes = inspector.get_indexes(TABLE_NAME)
    
    idx_active_mobula_exists = any(idx['name'] == 'idx_alerts_active_token_mobula_id' for idx in indexes)
    if idx_active_mobula_exists:
        op.drop_index('idx_alerts_active_token_mobula_id', table_name=TABLE_NAME)
        logger.info(f"Dropped index 'idx_alerts_active_token_mobula_id' from '{TABLE_NAME}'.")
    else:
        logger.info(f"Index 'idx_alerts_active_token_mobula_id' not found, skipping drop.")

    # For auto-named index ix_alerts_token_mobula_id (from index=True on column)
    # The op.f('ix_alerts_token_mobula_id') generates the conventional name.
    auto_named_idx_mobula = op.f('ix_alerts_token_mobula_id')
    idx_auto_mobula_exists = any(idx['name'] == auto_named_idx_mobula for idx in indexes)
    if idx_auto_mobula_exists:
        op.drop_index(auto_named_idx_mobula, table_name=TABLE_NAME)
        logger.info(f"Dropped auto-named index '{auto_named_idx_mobula}' for 'token_mobula_id' from '{TABLE_NAME}'.")
    else:
        logger.info(f"Auto-named index '{auto_named_idx_mobula}' for 'token_mobula_id' not found, skipping drop.")
        
    op.drop_column(TABLE_NAME, 'token_mobula_id')
    logger.info(f"Dropped column 'token_mobula_id' from '{TABLE_NAME}'.")

    # 5. Modify token_display_name to be nullable=False -- This is done in Step 4 now.

    # Step 6. Update 'check_token_price_alert_fields' constraint
    conn_check_upgrade = op.get_bind()
    inspector_check_upgrade = sa.inspect(conn_check_upgrade)
    check_constraints_upgrade = inspector_check_upgrade.get_check_constraints(TABLE_NAME)
    
    constraint_to_drop_exists = any(c['name'] == OLD_TOKEN_PRICE_FIELDS_CONSTRAINT_NAME for c in check_constraints_upgrade)
    
    if constraint_to_drop_exists:
        op.drop_constraint(OLD_TOKEN_PRICE_FIELDS_CONSTRAINT_NAME, TABLE_NAME, type_='check')
        logger.info(f"Dropped constraint '{OLD_TOKEN_PRICE_FIELDS_CONSTRAINT_NAME}' from '{TABLE_NAME}'.")
    else:
        logger.warning(f"Constraint '{OLD_TOKEN_PRICE_FIELDS_CONSTRAINT_NAME}' not found on '{TABLE_NAME}' during upgrade, skipping drop. This might be okay.")

    op.create_check_constraint(
        OLD_TOKEN_PRICE_FIELDS_CONSTRAINT_NAME, 
        TABLE_NAME,
        sa.text("(cmc_id IS NOT NULL AND token_display_name IS NOT NULL)") # Condition now refers to cmc_id
    )
    logger.info(f"Created/Updated constraint '{OLD_TOKEN_PRICE_FIELDS_CONSTRAINT_NAME}' on '{TABLE_NAME}' to use cmc_id.")


def downgrade() -> None:
    logger.info(f"Reverting CoinMarketCap integration changes for '{TABLE_NAME}' table.")

    # 1. Revert 'check_token_price_alert_fields' constraint
    conn_check_downgrade = op.get_bind()
    inspector_check_downgrade = sa.inspect(conn_check_downgrade)
    check_constraints_downgrade = inspector_check_downgrade.get_check_constraints(TABLE_NAME)
    
    constraint_to_revert_exists = any(c['name'] == OLD_TOKEN_PRICE_FIELDS_CONSTRAINT_NAME for c in check_constraints_downgrade)

    if constraint_to_revert_exists:
        op.drop_constraint(OLD_TOKEN_PRICE_FIELDS_CONSTRAINT_NAME, TABLE_NAME, type_='check')
        logger.info(f"Dropped constraint '{OLD_TOKEN_PRICE_FIELDS_CONSTRAINT_NAME}' from '{TABLE_NAME}' during downgrade.")
    else:
        logger.warning(f"Constraint '{OLD_TOKEN_PRICE_FIELDS_CONSTRAINT_NAME}' not found on '{TABLE_NAME}' during downgrade, skipping drop before recreate.")
        
    # Recreate with the logic it had after migration f67257373be9 (which was based on mobula_id)
    # This assumes token_mobula_id column will be re-added by this downgrade.
    op.create_check_constraint(
        OLD_TOKEN_PRICE_FIELDS_CONSTRAINT_NAME,
        TABLE_NAME,
        # This was the state after f67257373be9 simplified it for mobula_id only
        # sa.text("(token_mobula_id IS NOT NULL AND token_display_name IS NOT NULL)")
        # However, to be more robust for downgrade, let's use the original definition from e97bbf94c241
        # which was "(alert_type != 'token_price') OR (token_mobula_id IS NOT NULL AND token_display_name IS NOT NULL)"
        # This is safer as it accounts for alert_type if it's also reverted.
        sa.text("(alert_type != 'token_price') OR (token_mobula_id IS NOT NULL AND token_display_name IS NOT NULL)")
    )
    logger.info(f"Reverted constraint '{OLD_TOKEN_PRICE_FIELDS_CONSTRAINT_NAME}' to its pre-CMC state (expecting mobula_id).")

    # 2. Modify token_display_name back to nullable=True (as it was after e97bbf94c241)
    op.alter_column(TABLE_NAME, 'token_display_name', existing_type=sa.String(length=255), nullable=True)
    logger.info(f"Altered column 'token_display_name' in '{TABLE_NAME}' back to nullable.")

    # 3. Re-add token_mobula_id column (nullable=True) and its indexes
    op.add_column(TABLE_NAME, sa.Column('token_mobula_id', sa.BigInteger(), nullable=True))
    op.create_index(op.f('ix_alerts_token_mobula_id'), TABLE_NAME, ['token_mobula_id'], unique=False) 
    op.create_index('idx_alerts_active_token_mobula_id', TABLE_NAME, ['is_active', 'token_mobula_id'], unique=False, postgresql_where=sa.text("alert_type = 'token_price'"))
    logger.info(f"Re-added column 'token_mobula_id' and its indexes to '{TABLE_NAME}'.")

    # 4. Drop cmc_id column and its indexes
    # Use inspector for downgrade as well for robustness
    conn_dg = op.get_bind()
    inspector_dg = sa.inspect(conn_dg)
    indexes_dg = inspector_dg.get_indexes(TABLE_NAME)

    if any(idx['name'] == 'idx_alerts_active_cmc_id' for idx in indexes_dg):
        op.drop_index('idx_alerts_active_cmc_id', table_name=TABLE_NAME)
    if any(idx['name'] == 'idx_alerts_cmc_id' for idx in indexes_dg):
        op.drop_index('idx_alerts_cmc_id', table_name=TABLE_NAME)
        
    op.drop_column(TABLE_NAME, 'cmc_id')
    logger.info(f"Dropped column 'cmc_id' and its indexes from '{TABLE_NAME}'.")
