# models.py

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, JSON, Table,
    BigInteger, Text, CheckConstraint, UniqueConstraint, Index, func, Float
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

# --- REMOVE this explicit Table definition ---
# portfolio_wallets_association = Table(
#     'portfolio_wallets',
#     # ... definition ...
# )
# --- END REMOVAL ---

class User(Base):
    """User model representing a Telegram user."""
    __tablename__ = 'users'

    user_id = Column(BigInteger, primary_key=True)
    username = Column(String(255), index=True, nullable=True)
    first_name = Column(String(255), nullable=True)
    is_premium = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    settings = Column(JSONB, nullable=True) # Using JSONB for PostgreSQL

    # Relationships (these remain largely the same, pointing to the main models)
    portfolios = relationship("Portfolio", back_populates="user", cascade="all, delete-orphan")
    wallets = relationship("Wallet", back_populates="user", cascade="all, delete-orphan")
    tracked_wallets = relationship("TrackedWallet", back_populates="user", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="user", cascade="all, delete-orphan")
    portfolio_snapshots = relationship("PortfolioSnapshot", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_users_username', 'username'), # Corrected Index definition syntax
    )

class Portfolio(Base):
    """Portfolio model for grouping multiple wallets."""
    __tablename__ = 'portfolios'

    portfolio_id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="portfolios")
    # --- REMOVE the relationship using secondary ---
    # associated_wallets = relationship(
    #     "Wallet",
    #     secondary=portfolio_wallets_association, # This caused the error because the Table object is removed
    #     back_populates="associated_portfolios"
    # )
    # --- KEEP the relationship TO the association object ---
    wallet_associations = relationship("PortfolioWalletAssociation", back_populates="portfolio", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="portfolio", cascade="all, delete-orphan")
    portfolio_snapshots = relationship("PortfolioSnapshot", back_populates="portfolio", cascade="all, delete-orphan", order_by="PortfolioSnapshot.timestamp")

    __table_args__ = (
        UniqueConstraint('user_id', 'name', name='uq_user_portfolio_name'),
        Index('idx_portfolios_user_id', 'user_id'), # Corrected Index definition syntax
    )

class Wallet(Base):
    """Wallet model representing a user's crypto wallet address identity."""
    __tablename__ = 'wallets'

    wallet_id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    address = Column(String(255), nullable=False, index=True)
    wallet_type = Column(String(20), nullable=False) # e.g., 'evm', 'solana', 'other'
    label = Column(String(100), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="wallets")
    # --- REMOVE the relationship using secondary ---
    # associated_portfolios = relationship(
    #     "Portfolio",
    #     secondary=portfolio_wallets_association, # This caused the error
    #     back_populates="associated_wallets"
    # )
    # --- KEEP the relationship TO the association object ---
    portfolio_associations = relationship("PortfolioWalletAssociation", back_populates="wallet", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="wallet", cascade="all, delete-orphan")
    portfolio_snapshots = relationship("PortfolioSnapshot", back_populates="wallet", cascade="all, delete-orphan", order_by="PortfolioSnapshot.timestamp")

    __table_args__ = (
        CheckConstraint(wallet_type.in_(['evm', 'solana', 'other']), name='check_wallet_type'),
        UniqueConstraint('user_id', 'address', name='uq_user_wallet_address'),
        Index('idx_wallets_user_id', 'user_id'), # Corrected Index definition syntax
        Index('idx_wallets_address', 'address'), # Corrected Index definition syntax
    )

# --- THIS CLASS NOW DEFINES the 'portfolio_wallets' table ---
class PortfolioWalletAssociation(Base):
    """Represents the association between a Portfolio, a Wallet, and a specific Chain."""
    __tablename__ = 'portfolio_wallets' # This name MUST match the table name in your SQL

    # Define a separate primary key for the association table itself
    association_id = Column(Integer, primary_key=True) # New simple primary key

    # Foreign keys remain, but are not part of the primary key anymore unless explicitly defined
    portfolio_id = Column(Integer, ForeignKey('portfolios.portfolio_id', ondelete='CASCADE'), nullable=False)
    wallet_id = Column(Integer, ForeignKey('wallets.wallet_id', ondelete='CASCADE'), nullable=False)
    # Chain is now optional
    chain = Column(String(50), nullable=True) # No longer primary key, allows NULL
    added_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    # Relationships to easily access Portfolio and Wallet objects *from* the association object
    portfolio = relationship("Portfolio", back_populates="wallet_associations")
    wallet = relationship("Wallet", back_populates="portfolio_associations")

    # Define indexes and constraints
    __table_args__ = (
        # Ensure a wallet can only be added once per portfolio, either generically (NULL chain)
        # or for a specific chain.
        UniqueConstraint('portfolio_id', 'wallet_id', 'chain', name='uq_portfolio_wallet_chain'),
        Index('idx_portfolio_wallets_portfolio_id', 'portfolio_id'),
        Index('idx_portfolio_wallets_wallet_id', 'wallet_id'),
        Index('idx_portfolio_wallets_chain', 'chain'), # Index on chain might be useful
        Index('idx_portfolio_wallets_wallet_chain', 'wallet_id', 'chain'),
    )


class TrackedWallet(Base):
    """Model for externally tracked wallets (not necessarily owned by the user)."""
    __tablename__ = 'tracked_wallets'

    tracked_wallet_id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    address = Column(String(255), nullable=False, index=True)
    wallet_type = Column(String(20), nullable=False) # e.g., 'evm', 'solana', 'other'
    label = Column(String(100), nullable=True)
    alerts_enabled = Column(Boolean, nullable=False, default=False) # For tx alerts
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="tracked_wallets")
    alerts = relationship("Alert", back_populates="tracked_wallet", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(wallet_type.in_(['evm', 'solana', 'other']), name='check_tracked_wallet_type'),
        UniqueConstraint('user_id', 'address', name='uq_user_tracked_wallet_address'),
        Index('idx_tracked_wallets_user_id', 'user_id'), # Corrected Index definition syntax
        Index('idx_tracked_wallets_address', 'address'), # Corrected Index definition syntax
    )

class Alert(Base):
    """Alert model for price, portfolio value, and transaction notifications."""
    __tablename__ = 'alerts'

    alert_id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    alert_type = Column(String(50), nullable=False)
    conditions = Column(JSONB, nullable=False) # Store alert conditions as JSONB
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    last_triggered_at = Column(TIMESTAMP(timezone=True), nullable=True)
    trigger_count = Column(Integer, nullable=False, default=0)

    # Nullable Foreign Keys
    portfolio_id = Column(Integer, ForeignKey('portfolios.portfolio_id', ondelete='CASCADE'), nullable=True, index=True)
    wallet_id = Column(Integer, ForeignKey('wallets.wallet_id', ondelete='CASCADE'), nullable=True, index=True) # Refers to user's wallet identity
    tracked_wallet_id = Column(Integer, ForeignKey('tracked_wallets.tracked_wallet_id', ondelete='CASCADE'), nullable=True, index=True) # Refers to tracked wallet identity

    # Relationships
    user = relationship("User", back_populates="alerts")
    portfolio = relationship("Portfolio", back_populates="alerts")
    wallet = relationship("Wallet", back_populates="alerts")
    tracked_wallet = relationship("TrackedWallet", back_populates="alerts")

    __table_args__ = (
        CheckConstraint(alert_type.in_(['price', 'portfolio_value', 'wallet_tx', 'tracked_wallet_tx']), name='check_alert_type'),
        # The complex CHECK constraint 'check_alert_fk' from SQL is harder to represent directly
        # in SQLAlchemy's declarative layer. It's often handled in application logic or
        # potentially with a database-level constraint added separately via migrations.
        Index('idx_alerts_user_id', 'user_id'), # Added explicit index definition
        Index('idx_alerts_portfolio_id', 'portfolio_id'), # Added explicit index definition
        Index('idx_alerts_wallet_id', 'wallet_id'), # Added explicit index definition
        Index('idx_alerts_tracked_wallet_id', 'tracked_wallet_id'), # Added explicit index definition
        Index('idx_alerts_active_type_partial', 'alert_type', postgresql_where=(is_active == True)), # Corrected syntax
        Index('idx_alerts_conditions_gin', 'conditions', postgresql_using='gin', postgresql_ops={'conditions': 'jsonb_path_ops'}),
    )

class PortfolioSnapshot(Base):
    """Model for storing portfolio/wallet value snapshots."""
    __tablename__ = 'portfolio_snapshots'

    snapshot_id = Column(Integer, primary_key=True)
    # Link to the user who owns the data
    user_id = Column(BigInteger, ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)

    # Link to EITHER the specific portfolio OR the specific wallet identity this snapshot is for
    portfolio_id = Column(Integer, ForeignKey('portfolios.portfolio_id', ondelete='CASCADE'), nullable=True, index=True)
    wallet_id = Column(Integer, ForeignKey('wallets.wallet_id', ondelete='CASCADE'), nullable=True, index=True) # Links to Wallet identity

    # Timestamp of the snapshot
    timestamp = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), index=True)
    # Financial data - Float is usually sufficient, consider Numeric if extreme precision needed
    total_value = Column(Float, nullable=False)
    # Detailed token breakdown at the time of snapshot
    token_balances = Column(JSONB, nullable=False) # Use JSONB for efficiency

    # Relationships
    user = relationship("User", back_populates="portfolio_snapshots")
    portfolio = relationship("Portfolio", back_populates="portfolio_snapshots")
    wallet = relationship("Wallet", back_populates="portfolio_snapshots")

    # Ensure only one of portfolio_id or wallet_id is set (or both are null, though less useful)
    # This check constraint is good practice
    __table_args__ = (
        CheckConstraint(
            '(portfolio_id IS NOT NULL AND wallet_id IS NULL) OR '
            '(portfolio_id IS NULL AND wallet_id IS NOT NULL) OR '
            '(portfolio_id IS NULL AND wallet_id IS NULL)', # Allow snapshots not tied to either? Less common.
            name='check_snapshot_target'
        ),
         Index('idx_snapshot_user_target_time', 'user_id', 'portfolio_id', 'wallet_id', timestamp.desc()), # Corrected Index definition syntax
         Index('idx_portfolio_snapshots_user_id', 'user_id'), # Added explicit indexes
         Index('idx_portfolio_snapshots_portfolio_id', 'portfolio_id'),
         Index('idx_portfolio_snapshots_wallet_id', 'wallet_id'),
         Index('idx_portfolio_snapshots_timestamp', 'timestamp'),
    )
