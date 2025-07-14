from sqlalchemy import create_engine, delete, update, func
from sqlalchemy.orm import sessionmaker, joinedload
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.future import select
# Import 'is_' for NULL checks if needed, though SQLAlchemy handles None comparison well
# from sqlalchemy import and_, or_, is_
from models import Base, User, Wallet, Alert, TrackedWallet
from typing import List, Optional, Dict, Any
import json
import logging # Added logging
from datetime import datetime, timezone, timedelta # Added for timestamping
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

    async def create_user(self, user_id: int, username: Optional[str] = None, first_name: Optional[str] = None) -> tuple[User, bool]:
        """Create a new user or get existing one, updating details if changed.

        Returns:
            A tuple containing the User object and a boolean indicating if the user was newly created.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(User).where(User.user_id == user_id)
            )
            user = result.scalar_one_or_none()
            is_new_user = False

            if not user:
                is_new_user = True
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


            return user, is_new_user

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
        Relies on cascade deletes for related Alerts, etc.
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
                # - Alerts linked via wallet_id
                await session.delete(wallet)
                await session.commit()
                logger.info(f"Successfully deleted wallet identity ID {wallet_id} (Address: {wallet.address}) for user {user_id}.")
                return True
            except Exception as e:
                 logger.error(f"Error deleting wallet identity ID {wallet_id} for user {user_id}: {e}")
                 await session.rollback()
                 return False

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

    async def get_all_users_by_activity(self) -> List[User]:
        """Get all users from the database, sorted by last activity (most recent first)."""
        async with self.async_session() as session:
            # We define "last active" as the more recent of `last_api_call_at` and `updated_at`.
            # `last_api_call_at` can be NULL. `updated_at` is not.
            # `func.greatest` in PostgreSQL handles NULLs by ignoring them if other arguments are not null.
            # So `greatest(non_null, null)` returns `non_null`. This is what we want.
            stmt = select(User).order_by(
                func.greatest(User.updated_at, User.last_api_call_at).desc().nulls_last()
            )
            result = await session.execute(stmt)
            return result.scalars().all()

    async def get_active_alerts(self) -> List[Alert]:
        """Get all active alerts."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Alert).where(Alert.is_active == True)
                .options( # Eager load related objects needed for alert checking
                     joinedload(Alert.user),
                     joinedload(Alert.wallet),
                     joinedload(Alert.tracked_wallet)
                     )
            )
            return result.scalars().all()

    # --- New Token Price Alert Methods ---

    async def get_active_token_price_alerts(self) -> List[Alert]:
        """Selects all active 'token_price' alerts from CMC."""
        async with self.async_session() as session:
            stmt = (
                select(Alert)
                .where(Alert.alert_type == 'token_price', Alert.is_active == True, Alert.source == 'cmc')
                .options(joinedload(Alert.user)) # Eager load user for notifications
            )
            result = await session.execute(stmt)
            return result.scalars().all()

    async def get_active_coingecko_token_price_alerts(self) -> List[Alert]:
        """Selects all active 'token_price' alerts from CoinGecko."""
        async with self.async_session() as session:
            stmt = (
                select(Alert)
                .where(Alert.alert_type == 'token_price', Alert.is_active == True, Alert.source == 'coingecko')
                .options(joinedload(Alert.user))
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
        cmc_id: int,
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
                "condition": condition.lower(),
                "label": label or f"{token_display_name} {condition} ${target_price:g}"
            }

            new_alert = Alert(
                user_id=user_id,
                alert_type='token_price',
                source='cmc', # Explicitly set source
                conditions=alert_conditions,
                cmc_id=cmc_id,
                token_display_name=token_display_name,
                is_active=True,
                trigger_count=0
            )
            session.add(new_alert)
            try:
                await session.commit()
                await session.refresh(new_alert)
                logger.info(f"Created CMC token price alert for user {user_id}, CMC ID {cmc_id}, label '{label}'. Alert ID: {new_alert.alert_id}")
                return new_alert
            except Exception as e:
                logger.error(f"Error creating CMC token price alert for user {user_id}, CMC ID {cmc_id}: {e}")
                await session.rollback()
                return None

    async def create_coingecko_token_price_alert(
        self,
        user_id: int,
        token_address: str,
        network_id: str,
        token_display_name: str,
        target_price: float,
        condition: str,
        label: Optional[str] = None,
        polling_interval: int = 210 # Default 3.5 minutes
    ) -> Optional[Alert]:
        """Creates a new 'token_price' alert using CoinGecko data."""
        async with self.async_session() as session:
            if condition.lower() not in ['above', 'below']:
                logger.error(f"Invalid condition '{condition}' for CoinGecko alert for user {user_id}.")
                return None

            alert_conditions = {
                "target_price": target_price,
                "condition": condition.lower(),
                "label": label or f"{token_display_name} {condition} ${target_price:g}"
            }

            new_alert = Alert(
                user_id=user_id,
                alert_type='token_price',
                source='coingecko',
                conditions=alert_conditions,
                token_address=token_address,
                network_id=network_id,
                token_display_name=token_display_name,
                is_active=True,
                trigger_count=0,
                polling_interval_seconds=polling_interval
            )
            session.add(new_alert)
            try:
                await session.commit()
                await session.refresh(new_alert)
                logger.info(f"Created CoinGecko alert for user {user_id}, Address {token_address} on {network_id}. Alert ID: {new_alert.alert_id}")
                return new_alert
            except Exception as e:
                logger.error(f"Error creating CoinGecko alert for user {user_id}, Address {token_address}: {e}")
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

    async def reactivate_alert(self, alert_id: int, new_condition: str, new_target_price: float) -> bool:
        """Reactivates a specific alert with a new price condition."""
        async with self.async_session() as session:
            alert = await session.get(Alert, alert_id)
            if not alert:
                logger.warning(f"Alert ID {alert_id} not found for reactivation.")
                return False

            if alert.alert_type != 'token_price':
                logger.warning(f"Attempted to reactivate non-token-price alert ID {alert_id}.")
                return False

            # Update conditions with new price and condition
            new_conditions = alert.conditions.copy()
            new_conditions['target_price'] = new_target_price
            new_conditions['condition'] = new_condition.lower()

            alert.conditions = new_conditions
            alert.is_active = True
            alert.last_triggered_at = None # Reset trigger info
            alert.last_triggered_price = None

            try:
                await session.commit()
                logger.info(f"Successfully reactivated alert ID {alert_id} with new condition: {new_condition} {new_target_price}.")
                return True
            except Exception as e:
                logger.error(f"Error reactivating alert ID {alert_id}: {e}")
                await session.rollback()
                return False
            
    async def set_user_premium_status(self, user_id: int, is_premium: bool, days: Optional[int] = None) -> Optional[User]:
        """Sets the premium status for a given user ID."""
        async with self.async_session() as session:
            user = await session.get(User, user_id)
            if not user:
                logger.warning(f"Could not set premium status. User not found: {user_id}")
                return None
            
            user.is_premium = is_premium
            if is_premium:
                user.premium_start_date = datetime.now(timezone.utc)
                if days:
                    user.premium_expiry_date = datetime.now(timezone.utc) + timedelta(days=days)
                else:
                    user.premium_expiry_date = None # Or a far future date for permanent premium
            else:
                user.premium_start_date = None
                user.premium_expiry_date = None

            await session.commit()
            await session.refresh(user)
            logger.info(f"Set premium status for user {user_id} to {is_premium}.")
            return user

    async def get_expired_premium_users(self) -> List[User]:
        """Get all users whose premium has expired."""
        async with self.async_session() as session:
            now = datetime.now(timezone.utc)
            result = await session.execute(
                select(User).where(
                    User.is_premium == True,
                    User.premium_expiry_date != None,
                    User.premium_expiry_date < now
                )
            )
            return result.scalars().all()
