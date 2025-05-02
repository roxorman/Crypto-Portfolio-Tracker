from sqlalchemy import create_engine, delete, update
from sqlalchemy.orm import sessionmaker, joinedload
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.future import select
#from sqlalchemy import and_, or_, is_ # Import is_ for NULL checks
from models import Base, User, Portfolio, Wallet, Alert, TrackedWallet , PortfolioWalletAssociation
from typing import List, Optional
import json

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

    # Create close_engine method to close the engine when done
    async def close_engine(self):
        """Close the database engine."""
        await self.engine.dispose()

    async def create_user(self, user_id: int, username: Optional[str] = None, first_name: Optional[str] = None) -> User:
        """Create a new user or get existing one."""
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
            else:
                # Update username/first_name if provided and different
                if username is not None and user.username != username:
                    user.username = username
                if first_name is not None and user.first_name != first_name:
                    user.first_name = first_name
                await session.commit()

            return user

    async def create_portfolio(self, user_id: int, name: str, description: str = "") -> Optional[Portfolio]:
        """Create a new portfolio."""
        async with self.async_session() as session:
            # Check for existing portfolio with the same name for this user
            existing_portfolio = await self.get_portfolio_by_name(user_id, name)
            if existing_portfolio:
                return None # Portfolio with this name already exists for this user

            portfolio = Portfolio(
                user_id=user_id,
                name=name,
                description=description,
            )
            session.add(portfolio)
            await session.commit()
            await session.refresh(portfolio)
            return portfolio

    async def get_user_portfolios(self, user_id: int) -> List[Portfolio]:
        """Get all portfolios for a user."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Portfolio)
                .where(Portfolio.user_id == user_id)
                .order_by(Portfolio.created_at)
            )
            return result.scalars().all()

    async def get_portfolio_by_name(self, user_id: int, name: str) -> Optional[Portfolio]:
        """Get a portfolio by name for a user."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Portfolio)
                .where(Portfolio.user_id == user_id)
                .where(Portfolio.name == name)
            )
            return result.scalar_one_or_none()

    async def get_portfolio_by_id(self, portfolio_id: int) -> Optional[Portfolio]:
        """Get a portfolio by ID."""
        async with self.async_session() as session:
            return await session.get(Portfolio, portfolio_id)

    async def delete_portfolio(self, user_id: int, name: str) -> bool:
        """Delete a portfolio by name."""
        async with self.async_session() as session:
            portfolio = await self.get_portfolio_by_name(user_id, name)
            if not portfolio:
                return False
            
            # SQLAlchemy's cascade='all, delete-orphan' on relationships should handle
            # deleting associated wallet_associations and alerts automatically.
            
            await session.delete(portfolio)
            await session.commit()
            return True

    async def rename_portfolio(self, user_id: int, old_name: str, new_name: str) -> bool:
        """Rename a portfolio."""
        async with self.async_session() as session:
            # Check if a portfolio with the new name already exists for this user
            existing_portfolio = await self.get_portfolio_by_name(user_id, new_name)
            if existing_portfolio:
                return False # Cannot rename to a name that already exists

            portfolio = await self.get_portfolio_by_name(user_id, old_name)
            if not portfolio:
                return False
            
            portfolio.name = new_name
            await session.commit()
            return True

    async def add_wallet_identity(self, user_id: int, address: str, wallet_type: str, label: Optional[str] = None) -> Wallet:
        """Add a new wallet identity for a user or get existing one."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Wallet)
                .where(Wallet.user_id == user_id)
                .where(Wallet.address == address.lower())
            )
            wallet = result.scalar_one_or_none()
            
            if not wallet:
                wallet = Wallet(
                    user_id=user_id,
                    address=address.lower(),
                    wallet_type=wallet_type,
                    label=label
                )
                session.add(wallet)
                await session.commit()
                await session.refresh(wallet)
            else:
                 # Update label if provided and different
                if label is not None and wallet.label != label:
                    wallet.label = label
                    await session.commit()
            
            return wallet

    async def get_user_wallets(self, user_id: int) -> List[Wallet]:
        """Get all wallet identities for a user."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Wallet)
                .where(Wallet.user_id == user_id)
                .order_by(Wallet.created_at)
            )
            return result.scalars().all()

    async def get_wallet_by_address(self, user_id: int, address: str) -> Optional[Wallet]:
        """Get a user's wallet identity by address."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Wallet)
                .where(Wallet.user_id == user_id)
                .where(Wallet.address == address.lower())
            )
            return result.scalar_one_or_none()

    async def get_wallet_by_label(self, user_id: int, label: str) -> Optional[Wallet]:
        """Get a user's wallet identity by label."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Wallet)
                .where(Wallet.user_id == user_id)
                .where(Wallet.label == label)
            )
            return result.scalar_one_or_none()

    async def find_user_wallet(self, user_id: int, identifier: str) -> Optional[Wallet]:
        """Find a user's wallet identity by address or label."""
        async with self.async_session() as session:
            # Prioritize address lookup
            if identifier.startswith('0x') or len(identifier) > 30: # Basic heuristic for address
                 result = await session.execute(
                    select(Wallet)
                    .where(Wallet.user_id == user_id)
                    .where(Wallet.address == identifier.lower())
                 )
                 wallet = result.scalar_one_or_none()
                 if wallet:
                     return wallet
        
            # Then try label lookup
            result = await session.execute(
                select(Wallet)
                .where(Wallet.user_id == user_id)
                .where(Wallet.label == identifier)
            )
            return result.scalar_one_or_none()

    async def get_portfolio_wallet_associations(self, portfolio_id: int) -> List[PortfolioWalletAssociation]:
        """Get all wallet associations for a portfolio, eagerly loading the Wallet object."""
        async with self.async_session() as session:
            result = await session.execute(
                select(PortfolioWalletAssociation)
                .where(PortfolioWalletAssociation.portfolio_id == portfolio_id)
                .options(joinedload(PortfolioWalletAssociation.wallet)) # Eagerly load Wallet
            )
            return result.scalars().all()

    async def add_wallet_to_portfolio(self, portfolio_id: int, wallet_id: int, chain: Optional[str]) -> bool:
        """Add a wallet identity (optionally on a specific chain) to a portfolio."""
        async with self.async_session() as session:
            try:
                # Check if the association already exists (handles chain being None or a string)
                stmt = select(PortfolioWalletAssociation).where(
                    PortfolioWalletAssociation.portfolio_id == portfolio_id,
                    PortfolioWalletAssociation.wallet_id == wallet_id
                )
                if chain is None:
                    stmt = stmt.where(PortfolioWalletAssociation.chain.is_(None))
                else:
                    stmt = stmt.where(PortfolioWalletAssociation.chain == chain)

                existing_association = await session.execute(stmt)
                if existing_association.scalar_one_or_none():
                    return False # Association already exists

                association = PortfolioWalletAssociation(
                    portfolio_id=portfolio_id,
                    wallet_id=wallet_id,
                    chain=chain
                )
                session.add(association)
                await session.commit()
                return True
            except Exception as e:
                print(f"Error adding wallet to portfolio: {e}")
                return False

    async def remove_wallet_from_portfolio(self, portfolio_id: int, wallet_id: int, chain: Optional[str]) -> bool:
        """Remove a wallet identity (optionally on a specific chain) from a portfolio."""
        async with self.async_session() as session:
            try:
                stmt = delete(PortfolioWalletAssociation).where(
                    PortfolioWalletAssociation.portfolio_id == portfolio_id,
                    PortfolioWalletAssociation.wallet_id == wallet_id
                )
                if chain is None:
                    stmt = stmt.where(PortfolioWalletAssociation.chain.is_(None))
                else:
                    stmt = stmt.where(PortfolioWalletAssociation.chain == chain)

                result = await session.execute(stmt)
                await session.commit()
                return result.rowcount > 0
            except Exception as e:
                print(f"Error removing wallet from portfolio: {e}")
                return False

    async def create_alert(self, user_id: int, alert_type: str, conditions: dict,
                        portfolio_id: Optional[int] = None,
                        wallet_id: Optional[int] = None,
                        tracked_wallet_id: Optional[int] = None) -> Alert:
        """Create a new alert."""
        async with self.async_session() as session:
            alert = Alert(
                user_id=user_id,
                alert_type=alert_type,
                conditions=conditions,
                portfolio_id=portfolio_id,
                wallet_id=wallet_id,
                tracked_wallet_id=tracked_wallet_id
            )
            session.add(alert)
            await session.commit()
            await session.refresh(alert)
            return alert

    async def get_user_alerts(self, user_id: int) -> List[Alert]:
        """Get all active alerts for a user."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Alert)
                .where(Alert.user_id == user_id)
                .where(Alert.is_active == True)
                .order_by(Alert.created_at)
            )
            return result.scalars().all()

    async def get_alert_by_id(self, user_id: int, alert_id: int) -> Optional[Alert]:
        """Get a specific alert by ID for a user."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Alert)
                .where(Alert.user_id == user_id)
                .where(Alert.alert_id == alert_id)
            )
            return result.scalar_one_or_none()

    async def deactivate_alert(self, alert_id: int) -> bool:
        """Deactivate an alert."""
        async with self.async_session() as session:
            result = await session.execute(
                update(Alert)
                .where(Alert.alert_id == alert_id)
                .values(is_active=False)
            )
            await session.commit()
            return result.rowcount > 0

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
            )
            return result.scalars().all()

    async def get_wallet_by_id(self, wallet_id: int) -> Optional[Wallet]:
        """Get a wallet identity by ID."""
        async with self.async_session() as session:
            return await session.get(Wallet, wallet_id)

    # Methods for Tracked Wallets
    async def add_tracked_wallet(self, user_id: int, address: str, wallet_type: str, label: Optional[str] = None) -> Optional[TrackedWallet]:
        """Add a new tracked wallet for a user or get existing one."""
        async with self.async_session() as session:
            result = await session.execute(
                select(TrackedWallet)
                .where(TrackedWallet.user_id == user_id)
                .where(TrackedWallet.address == address.lower())
            )
            tracked_wallet = result.scalar_one_or_none()

            if not tracked_wallet:
                tracked_wallet = TrackedWallet(
                    user_id=user_id,
                    address=address.lower(),
                    wallet_type=wallet_type,
                    label=label
                )
                session.add(tracked_wallet)
                await session.commit()
                await session.refresh(tracked_wallet)
            else:
                 # Update label if provided and different
                if label is not None and tracked_wallet.label != label:
                    tracked_wallet.label = label
                    await session.commit()

            return tracked_wallet

    async def get_user_tracked_wallets(self, user_id: int) -> List[TrackedWallet]:
        """Get all tracked wallets for a user."""
        async with self.async_session() as session:
            result = await session.execute(
                select(TrackedWallet)
                .where(TrackedWallet.user_id == user_id)
                .order_by(TrackedWallet.created_at)
            )
            return result.scalars().all()

    async def find_user_tracked_wallet(self, user_id: int, identifier: str) -> Optional[TrackedWallet]:
        """Find a user's tracked wallet by address or label."""
        async with self.async_session() as session:
            # Prioritize address lookup
            if identifier.startswith('0x') or len(identifier) > 30: # Basic heuristic for address
                 tracked_wallet = await session.execute(
                    select(TrackedWallet)
                    .where(TrackedWallet.user_id == user_id)
                    .where(TrackedWallet.address == identifier.lower())
                 )
                 tracked_wallet = tracked_wallet.scalar_one_or_none()
                 if tracked_wallet:
                     return tracked_wallet

            # Then try label lookup
            result = await session.execute(
                select(TrackedWallet)
                .where(TrackedWallet.user_id == user_id)
                .where(TrackedWallet.label == identifier)
            )
            return result.scalar_one_or_none()

    async def remove_tracked_wallet(self, user_id: int, identifier: str) -> bool:
        """Remove a tracked wallet by address or label."""
        async with self.async_session() as session:
            tracked_wallet = await self.find_user_tracked_wallet(user_id, identifier)
            if not tracked_wallet:
                return False

            # SQLAlchemy's cascade='all, delete-orphan' on relationships should handle
            # deleting associated alerts automatically.

            await session.delete(tracked_wallet)
            await session.commit()
            return True

    async def toggle_tracked_wallet_alerts(self, user_id: int, identifier: str, enable: bool) -> bool:
        """Toggle alerts for a tracked wallet."""
        async with self.async_session() as session:
            tracked_wallet = await self.find_user_tracked_wallet(user_id, identifier)
            if not tracked_wallet:
                return False

            tracked_wallet.alerts_enabled = enable
            await session.commit()
            return True

    # Placeholder for snapshot methods (removed from models.py based on schema.sql)
    # If PortfolioSnapshot is added back, these methods will need implementation.
    async def save_portfolio_snapshot(self, user_id: int, total_value: float,
                                  token_balances: dict, wallet_id: Optional[int] = None,
                                  portfolio_id: Optional[int] = None):
        """Placeholder for saving portfolio snapshot."""
        pass # Implement if PortfolioSnapshot model is added back

    async def get_latest_snapshot(self, portfolio_id: int):
        """Placeholder for getting the latest snapshot."""
        pass # Implement if PortfolioSnapshot model is added back
