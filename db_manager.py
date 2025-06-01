from sqlalchemy import create_engine, delete, update
from sqlalchemy.orm import sessionmaker, joinedload
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.future import select
# Import 'is_' for NULL checks if needed, though SQLAlchemy handles None comparison well
# from sqlalchemy import and_, or_, is_
from models import Base, User, Portfolio, Wallet, Alert, TrackedWallet, PortfolioWalletAssociation
from typing import List, Optional, Dict, Any
import json
import logging # Added logging
from datetime import datetime, timezone # Added for timestamping
from web3 import Web3 # For address validation
import re # For regex matching

logger = logging.getLogger(__name__) # Added logger

class DatabaseManager:
    """Handles all database operations and interactions."""

    def __init__(self, database_url=None):
        self.engine = create_async_engine(database_url) if database_url else None
        self.async_session = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        ) if self.engine else None

    async def init_db(self):
        """Initialize the database and create tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close_engine(self):
        """Close the database engine."""
        if self.engine: # Check if engine exists
            await self.engine.dispose()

    async def create_user(self, user_id: int, username: Optional[str] = None, first_name: Optional[str] = None) -> User:
        """Create a new user or get existing one, updating details if changed."""
        async with self.async_session() as session:
            result = await session.execute(
                select(User).where(User.user_id == user_id)
            )
            user = result.scalar_one_or_none()

            if not user:
                user = User(
                    user_id=user_id,
                    username=username,
                    first_name=first_name,
                    settings={}
                )
                session.add(user)
                await session.commit()
                logger.info(f"Created new user: {user_id} ({username})")
            else:
                needs_commit = False
                if username is not None and user.username != username:
                    user.username = username
                    needs_commit = True
                    logger.info(f"Updating username for user: {user_id} to {username}")
                if first_name is not None and user.first_name != first_name:
                    user.first_name = first_name
                    needs_commit = True
                    logger.info(f"Updating first_name for user: {user_id} to {first_name}")
                if needs_commit:
                    await session.commit()
                else:
                     logger.debug(f"User {user_id} already exists with up-to-date info.")


            return user

    async def create_portfolio(self, user_id: int, name: str, description: str = "") -> Optional[Portfolio]:
        """Create a new portfolio."""
        async with self.async_session() as session:
            existing_portfolio = await self.get_portfolio_by_name(user_id, name)
            if existing_portfolio:
                logger.warning(f"Portfolio '{name}' already exists for user {user_id}.")
                return None

            portfolio = Portfolio(
                user_id=user_id,
                name=name,
                description=description,
            )
            session.add(portfolio)
            await session.commit()
            await session.refresh(portfolio)
            logger.info(f"Created portfolio '{name}' for user {user_id}.")
            return portfolio

    async def get_user_portfolios(self, user_id: int) -> List[Portfolio]:
        """Get all portfolios for a user, including wallet associations."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Portfolio)
                .where(Portfolio.user_id == user_id)
                # Eager load associations AND the wallet within each association
                .options(
                    joinedload(Portfolio.wallet_associations)
                    .joinedload(PortfolioWalletAssociation.wallet)
                    )
                .order_by(Portfolio.name) # Order portfolios by name
            )
            # Use unique() to handle potential duplicates if eager loading creates multiple rows per portfolio
            return result.scalars().unique().all()

    async def get_portfolio_by_name(self, user_id: int, name: str) -> Optional[Portfolio]:
        """Get a portfolio by name for a user."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Portfolio)
                .where(Portfolio.user_id == user_id, Portfolio.name == name)
            )
            return result.scalar_one_or_none()

    async def get_portfolio_by_id(self, portfolio_id: int) -> Optional[Portfolio]:
        """Get a portfolio by ID."""
        async with self.async_session() as session:
            return await session.get(Portfolio, portfolio_id)

    async def delete_portfolio(self, user_id: int, name: str) -> bool:
        """Delete a portfolio by name for a user."""
        async with self.async_session() as session:
            portfolio = await self.get_portfolio_by_name(user_id, name)
            if not portfolio:
                logger.warning(f"Portfolio '{name}' not found for user {user_id} during delete.")
                return False

            # Cascade should handle deleting PortfolioWalletAssociation entries.
            # Alerts linked via portfolio_id should also be handled by cascade.
            await session.delete(portfolio)
            await session.commit()
            logger.info(f"Deleted portfolio '{name}' (ID: {portfolio.portfolio_id}) for user {user_id}.")
            return True

    async def rename_portfolio(self, user_id: int, old_name: str, new_name: str) -> bool:
        """Rename a portfolio."""
        async with self.async_session() as session:
            existing_new = await self.get_portfolio_by_name(user_id, new_name)
            if existing_new:
                logger.warning(f"Cannot rename portfolio '{old_name}' to '{new_name}' for user {user_id}: new name already exists.")
                return False

            portfolio = await self.get_portfolio_by_name(user_id, old_name)
            if not portfolio:
                logger.warning(f"Portfolio '{old_name}' not found for user {user_id} during rename.")
                return False

            portfolio.name = new_name
            session.add(portfolio) # Explicitly add the modified object to the session
            try:
                await session.flush() # Try to flush changes to DB first
                logger.info(f"Successfully flushed rename of portfolio '{old_name}' to '{new_name}' for user {user_id}.")
                await session.commit()
                logger.info(f"Successfully committed rename of portfolio '{old_name}' to '{new_name}' for user {user_id}.")
                # Verify the change within the same session if possible, or re-fetch to be certain
                # For now, let's assume commit success means DB success.
                return True
            except Exception as e:
                logger.error(f"Error during commit for portfolio rename ({old_name} -> {new_name}) for user {user_id}: {e}")
                try:
                    await session.rollback()
                    logger.info(f"Session rolled back for portfolio rename failure: {old_name} -> {new_name}")
                except Exception as rb_e:
                    logger.error(f"Error during rollback for portfolio rename failure: {rb_e}")
                return False

    # --- Wallet Identity Management ---

    async def add_wallet_identity(self, user_id: int, address: str, label: Optional[str] = None) -> Optional[Wallet]:
        """Add a new wallet identity for a user. Returns None if it fails."""
        # Normalise address before storing/checking
        # For EVM addresses, this is lowercase. For others, it might be case-sensitive or have other rules.
        # Assuming Web3.is_address helps identify EVM-like addresses for now.
        # If not an EVM address, store as is. This might need refinement if other specific normalizations are needed.
        norm_address = address.lower() if Web3.is_address(address) else address

        async with self.async_session() as session:
            # Check if this exact address already exists for the user
            existing_wallet = await self.get_wallet_by_address(user_id, norm_address) # Use helper
            if existing_wallet:
                logger.warning(f"Wallet identity {norm_address} already exists for user {user_id}.")
                return existing_wallet

            try:
                wallet = Wallet(
                    user_id=user_id,
                    address=norm_address, # Store normalized address
                    # wallet_type field is removed from Wallet model
                    label=label
                )
                session.add(wallet)
                await session.commit()
                await session.refresh(wallet)
                logger.info(f"Added new wallet identity: {norm_address} (Label: {label}) for user {user_id}.")
                return wallet
            except Exception as e:
                 logger.error(f"Error adding wallet identity {norm_address} for user {user_id}: {e}")
                 await session.rollback() # Rollback on error
                 return None


    async def update_wallet_label(self, user_id: int, address: str, new_label: str) -> bool:
        """Updates the label for an existing wallet identity."""
        norm_address = address.lower() if Web3.is_address(address) else address # Normalize address for lookup
        async with self.async_session() as session:
            result = await session.execute(
                select(Wallet)
                .where(Wallet.user_id == user_id, Wallet.address == norm_address)
            )
            wallet = result.scalar_one_or_none()

            if not wallet:
                logger.warning(f"Wallet {norm_address} not found for user {user_id} during label update.")
                return False

            if wallet.label == new_label:
                 logger.info(f"Label for wallet {norm_address} is already '{new_label}'. No update needed.")
                 return True # No change needed, consider it success

            try:
                wallet.label = new_label
                await session.commit()
                logger.info(f"Updated label for wallet {norm_address} to '{new_label}' for user {user_id}.")
                return True
            except Exception as e:
                 logger.error(f"Error updating label for wallet {norm_address} for user {user_id}: {e}")
                 await session.rollback()
                 return False

    async def get_user_wallets(self, user_id: int) -> List[Wallet]:
        """Get all wallet identities for a user."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Wallet)
                .where(Wallet.user_id == user_id)
                .order_by(Wallet.label, Wallet.address) # Order consistently
            )
            return result.scalars().all()

    async def get_wallet_by_address(self, user_id: int, address: str) -> Optional[Wallet]:
        """Get a user's wallet identity by address (case-insensitive for EVM)."""
        # Normalize before querying
        norm_address = address.lower() if Web3.is_address(address) else address
        async with self.async_session() as session:
            result = await session.execute(
                select(Wallet)
                .where(Wallet.user_id == user_id, Wallet.address == norm_address)
            )
            return result.scalar_one_or_none()

    async def get_wallet_by_label(self, user_id: int, label: str) -> Optional[Wallet]:
        """Get a user's wallet identity by label (case-sensitive)."""
        async with self.async_session() as session:
            # Labels are typically case-sensitive unless normalized on input
            result = await session.execute(
                select(Wallet)
                .where(Wallet.user_id == user_id, Wallet.label == label)
            )
            # If multiple wallets have the same label, this might return only one.
            # Consider returning a list or adding a unique constraint if needed.
            return result.scalar_one_or_none()

    async def find_user_wallet(self, user_id: int, identifier: str) -> Optional[Wallet]:
        """Find a user's wallet identity by address (preferred) or label."""
        # 1. Try as address (normalized)
        is_potential_address = Web3.is_address(identifier) or re.fullmatch(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", identifier)
        if is_potential_address:
             wallet = await self.get_wallet_by_address(user_id, identifier)
             if wallet:
                 logger.debug(f"Found wallet for user {user_id} by address: {identifier}")
                 return wallet

        # 2. Try as label (case-sensitive)
        wallet = await self.get_wallet_by_label(user_id, identifier)
        if wallet:
            logger.debug(f"Found wallet for user {user_id} by label: {identifier}")
            return wallet

        logger.debug(f"Wallet identifier '{identifier}' not found for user {user_id} as address or label.")
        return None


    async def delete_wallet_identity(self, user_id: int, wallet_id: int) -> bool:
        """
        Deletes a specific Wallet identity by its ID for a given user.
        Relies on cascade deletes for related PortfolioWalletAssociation, Alerts, etc.
        """
        async with self.async_session() as session:
            # Fetch the wallet first to ensure it belongs to the user and exists
            wallet = await session.get(Wallet, wallet_id)

            if not wallet:
                logger.warning(f"Wallet ID {wallet_id} not found during delete attempt.")
                return False
            if wallet.user_id != user_id:
                logger.error(f"User {user_id} attempted to delete wallet ID {wallet_id} belonging to user {wallet.user_id}.")
                return False # Security check

            try:
                # Cascade should handle:
                # - PortfolioWalletAssociation entries linking this wallet
                # - Alerts linked via wallet_id
                # - PortfolioSnapshots linked via wallet_id
                await session.delete(wallet)
                await session.commit()
                logger.info(f"Successfully deleted wallet identity ID {wallet_id} (Address: {wallet.address}) for user {user_id}.")
                return True
            except Exception as e:
                 logger.error(f"Error deleting wallet identity ID {wallet_id} for user {user_id}: {e}")
                 await session.rollback()
                 return False


    # --- Portfolio <-> Wallet Association Management ---

    async def get_portfolio_wallet_associations(self, portfolio_id: int) -> List[PortfolioWalletAssociation]:
        """Get all wallet associations for a portfolio, eagerly loading the Wallet object."""
        async with self.async_session() as session:
            result = await session.execute(
                select(PortfolioWalletAssociation)
                .where(PortfolioWalletAssociation.portfolio_id == portfolio_id)
                .options(joinedload(PortfolioWalletAssociation.wallet)) # Eagerly load Wallet
                .order_by(PortfolioWalletAssociation.added_at) # Order by added time
            )
            return result.scalars().all()

    async def check_portfolio_wallet_link(self, portfolio_id: int, wallet_id: int) -> bool:
         """Checks if a specific portfolio-wallet link exists."""
         async with self.async_session() as session:
             stmt = select(PortfolioWalletAssociation.association_id).where(
                 PortfolioWalletAssociation.portfolio_id == portfolio_id,
                 PortfolioWalletAssociation.wallet_id == wallet_id
             )
             existing_association = await session.execute(stmt)
             return existing_association.scalar_one_or_none() is not None
         
    async def check_label_exists(self, user_id: int, label: str, exclude_wallet_id: Optional[int] = None) -> bool:
        """Checks if a label is already used by another wallet for the same user."""
        async with self.async_session() as session:
            stmt = select(Wallet.wallet_id).where(
                Wallet.user_id == user_id,
                Wallet.label == label
            )
            # If checking during a label update, exclude the wallet being updated
            if exclude_wallet_id is not None:
                stmt = stmt.where(Wallet.wallet_id != exclude_wallet_id)

            result = await session.execute(stmt)
            # If scalar_one_or_none finds *any* matching ID, the label exists elsewhere
            return result.scalar_one_or_none() is not None

    async def add_wallet_to_portfolio(self, portfolio_id: int, wallet_id: int) -> bool:
        """Add a wallet identity to a portfolio."""
        async with self.async_session() as session:
            # Check if the association already exists
            link_exists = await self.check_portfolio_wallet_link(portfolio_id, wallet_id)
            if link_exists:
                 logger.warning(f"Association already exists for PortfolioID:{portfolio_id}, WalletID:{wallet_id}")
                 return False # Indicate link already exists

            try:
                association = PortfolioWalletAssociation(
                    portfolio_id=portfolio_id,
                    wallet_id=wallet_id
                    # chain attribute removed
                )
                session.add(association)
                await session.commit()
                logger.info(f"Associated WalletID:{wallet_id} with PortfolioID:{portfolio_id}")
                return True
            except Exception as e:
                logger.error(f"Error associating WalletID:{wallet_id} with PortfolioID:{portfolio_id}: {e}")
                await session.rollback()
                return False # Indicate failure

    async def remove_wallet_from_portfolio(self, portfolio_id: int, wallet_id: int) -> bool:
        """Remove a wallet association from a portfolio."""
        async with self.async_session() as session:
            try:
                stmt = delete(PortfolioWalletAssociation).where(
                    PortfolioWalletAssociation.portfolio_id == portfolio_id,
                    PortfolioWalletAssociation.wallet_id == wallet_id
                )
                # chain attribute removed from where clause
                result = await session.execute(stmt)
                await session.commit()
                if result.rowcount > 0:
                    logger.info(f"Removed association for WalletID:{wallet_id} from PortfolioID:{portfolio_id}")
                    return True
                else:
                     logger.warning(f"No association found to remove for WalletID:{wallet_id}, PortfolioID:{portfolio_id}")
                     return False # Indicate nothing was removed
            except Exception as e:
                logger.error(f"Error removing association for WalletID:{wallet_id} from PortfolioID:{portfolio_id}: {e}")
                await session.rollback()
                return False # Indicate failure


    # --- Alert and Tracking Methods (Remain largely unchanged for now) ---
    # ... (create_alert, get_user_alerts, get_alert_by_id, deactivate_alert, etc.) ...
    # ... (get_all_users, get_active_alerts, get_wallet_by_id) ...
    # ... (add_tracked_wallet, get_user_tracked_wallets, find_user_tracked_wallet, etc.) ...
    # --- Snapshot Methods (Placeholders) ---
    # ... (save_portfolio_snapshot, get_latest_snapshot) ...

    # --- Keep methods needed by other modules ---
    async def get_wallet_by_id(self, wallet_id: int) -> Optional[Wallet]:
        """Get a wallet identity by ID."""
        async with self.async_session() as session:
            return await session.get(Wallet, wallet_id)

    async def get_all_users(self) -> List[User]:
        """Get all users from the database."""
        async with self.async_session() as session:
            result = await session.execute(select(User))
            return result.scalars().all()

    async def get_active_alerts(self) -> List[Alert]:
        """Get all active alerts."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Alert).where(Alert.is_active == True)
                .options( # Eager load related objects needed for alert checking
                     joinedload(Alert.user),
                     joinedload(Alert.portfolio),
                     joinedload(Alert.wallet),
                     joinedload(Alert.tracked_wallet)
                     )
            )
            return result.scalars().all()

    # --- New Token Price Alert Methods ---

    async def get_active_token_price_alerts(self) -> List[Alert]:
        """Selects all active 'token_price' alerts."""
        async with self.async_session() as session:
            stmt = (
                select(Alert)
                .where(Alert.alert_type == 'token_price', Alert.is_active == True)
                .options(joinedload(Alert.user)) # Eager load user for notifications
            )
            result = await session.execute(stmt)
            return result.scalars().all()

    async def deactivate_alert_and_log_trigger(self, alert_id: int, triggered_price: Optional[float] = None) -> bool:
        """
        Deactivates an alert, logs its trigger time, increments trigger count, and sets triggered price.
        """
        async with self.async_session() as session:
            alert = await session.get(Alert, alert_id)
            if not alert:
                logger.warning(f"Alert ID {alert_id} not found for deactivation.")
                return False
            
            if not alert.is_active:
                logger.info(f"Alert ID {alert_id} is already inactive. No action taken.")
                # Optionally return True if being already inactive is acceptable
                return True 

            alert.is_active = False
            alert.last_triggered_at = datetime.now(timezone.utc)
            alert.trigger_count = (alert.trigger_count or 0) + 1
            if triggered_price is not None:
                alert.last_triggered_price = triggered_price
            
            try:
                await session.commit()
                logger.info(f"Deactivated alert ID {alert_id}. Trigger count: {alert.trigger_count}, Triggered price: {triggered_price}.")
                return True
            except Exception as e:
                logger.error(f"Error deactivating alert ID {alert_id}: {e}")
                await session.rollback()
                return False

    async def create_token_price_alert(
        self, 
        user_id: int, 
        cmc_id: int,  # Changed from token_mobula_id to cmc_id
        token_display_name: str, 
        target_price: float, 
        condition: str, # "above" or "below"
        label: Optional[str] = None
    ) -> Optional[Alert]:
        """Creates a new 'token_price' alert using CoinMarketCap ID."""
        async with self.async_session() as session:
            # Validate condition
            if condition.lower() not in ['above', 'below']:
                logger.error(f"Invalid condition '{condition}' for token price alert for user {user_id}.")
                return None

            alert_conditions = {
                "target_price": target_price,
                "condition": condition.lower()
            }
            if label:
                alert_conditions["label"] = label

            new_alert = Alert(
                user_id=user_id,
                alert_type='token_price',
                conditions=alert_conditions,
                cmc_id=cmc_id,  # Use cmc_id
                token_display_name=token_display_name, # This is now non-nullable
                is_active=True,
                trigger_count=0
            )
            session.add(new_alert)
            try:
                await session.commit()
                await session.refresh(new_alert)
                logger.info(f"Created token price alert for user {user_id}, CMC ID {cmc_id}, label '{label}'. Alert ID: {new_alert.alert_id}")
                return new_alert
            except Exception as e:
                logger.error(f"Error creating token price alert for user {user_id}, CMC ID {cmc_id}: {e}")
                await session.rollback()
                return None

    async def get_user_token_price_alerts(self, user_id: int, only_active: bool = True) -> List[Alert]:
        """Retrieves token price alerts for a given user, optionally filtering by active status."""
        async with self.async_session() as session:
            stmt = select(Alert).where(
                Alert.user_id == user_id,
                Alert.alert_type == 'token_price'
            )
            if only_active:
                stmt = stmt.where(Alert.is_active == True)
            
            stmt = stmt.order_by(Alert.created_at.desc()) # Show newest first
            result = await session.execute(stmt)
            return result.scalars().all()

    async def find_user_token_price_alert_by_label(self, user_id: int, label: str) -> Optional[Alert]:
        """
        Finds an *active* token price alert for a user where conditions['label'] matches the input label.
        Note: JSONB key access might require specific syntax depending on SQLAlchemy version and dialect.
        This uses a simple string comparison assuming label is stored directly.
        For JSONB, you might need `Alert.conditions['label'].astext == label`.
        """
        async with self.async_session() as session:
            # Assuming label is stored as conditions -> 'label'
            # The .astext is important for comparing JSON string values in PostgreSQL
            stmt = select(Alert).where(
                Alert.user_id == user_id,
                Alert.alert_type == 'token_price',
                Alert.is_active == True, # Typically users want to delete active alerts by label
                Alert.conditions['label'].astext == label
            )
            result = await session.execute(stmt)
            alert = result.scalar_one_or_none()
            if alert:
                logger.info(f"Found active token price alert with label '{label}' for user {user_id}: Alert ID {alert.alert_id}")
            else:
                logger.info(f"No active token price alert found with label '{label}' for user {user_id}")
            return alert

    async def delete_alert_by_id(self, alert_id: int, user_id: int) -> bool:
        """Deletes an alert by its ID, ensuring it belongs to the requesting user."""
        async with self.async_session() as session:
            alert = await session.get(Alert, alert_id)
            if not alert:
                logger.warning(f"Alert ID {alert_id} not found for deletion.")
                return False
            
            if alert.user_id != user_id:
                logger.error(f"User {user_id} attempted to delete alert ID {alert_id} belonging to user {alert.user_id}.")
                return False # Security check: user can only delete their own alerts

            try:
                await session.delete(alert)
                await session.commit()
                logger.info(f"Successfully deleted alert ID {alert_id} for user {user_id}.")
                return True
            except Exception as e:
                logger.error(f"Error deleting alert ID {alert_id} for user {user_id}: {e}")
                await session.rollback()
                return False

    # --- Add other necessary Alert/TrackedWallet methods back if they were removed ---

# --- END OF MODIFIED FILE db_manager.py ---
