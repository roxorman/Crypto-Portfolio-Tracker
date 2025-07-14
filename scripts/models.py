# models.py

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, JSON, Table,
    BigInteger, Text, CheckConstraint, UniqueConstraint, Index, func, Float,
    and_, or_
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

class User(Base):
    """User model representing a Telegram user."""
    __tablename__ = 'users'

    user_id = Column(BigInteger, primary_key=True)
    username = Column(String(255), index=True, nullable=True)
    first_name = Column(String(255), nullable=True)
    is_premium = Column(Boolean, nullable=False, default=False)
    premium_start_date = Column(TIMESTAMP(timezone=True), nullable=True)
    premium_expiry_date = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    settings = Column(JSONB, nullable=True)

    # --- NEW FIELDS FOR RATE LIMITING ---
    api_call_count = Column(Integer, nullable=False, default=0)
    last_api_call_at = Column(TIMESTAMP(timezone=True), nullable=True)
    # --- END NEW FIELDS ---

    # Relationships
    wallets = relationship("Wallet", back_populates="user", cascade="all, delete-orphan")
    tracked_wallets = relationship("TrackedWallet", back_populates="user", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_users_username', 'username'), # Corrected Index definition syntax
    )

class Wallet(Base):
    """Wallet model representing a user's crypto wallet address identity."""
    __tablename__ = 'wallets'

    wallet_id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    address = Column(String(255), nullable=False, index=True)
    label = Column(String(100), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="wallets")
    
    __table_args__ = (
        UniqueConstraint('user_id', 'address', name='uq_user_wallet_address'),
        Index('idx_wallets_user_id', 'user_id'), # Corrected Index definition syntax
        Index('idx_wallets_address', 'address'), # Corrected Index definition syntax
    )

class TrackedWallet(Base):
    """Model for externally tracked wallets (not necessarily owned by the user)."""
    __tablename__ = 'tracked_wallets'

    tracked_wallet_id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    address = Column(String(255), nullable=False, index=True)
    label = Column(String(100), nullable=True)
    alerts_enabled = Column(Boolean, nullable=False, default=False) # For tx alerts
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="tracked_wallets")

    __table_args__ = (
        UniqueConstraint('user_id', 'address', name='uq_user_tracked_wallet_address'),
        Index('idx_tracked_wallets_user_id', 'user_id'), # Corrected Index definition syntax
        Index('idx_tracked_wallets_address', 'address'), # Corrected Index definition syntax
    )

class Alert(Base):
    """Alert model for price, portfolio value, and transaction notifications."""
    __tablename__ = 'alerts'

    alert_id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    alert_type = Column(String(50), nullable=False, index=True) # Added index
    conditions = Column(JSONB, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, index=True) # Added index
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    last_triggered_at = Column(TIMESTAMP(timezone=True), nullable=True)
    trigger_count = Column(Integer, nullable=False, default=0)

    # --- Fields for Token Price Alerts ---
    # Data source for the alert, e.g., 'cmc' or 'coingecko'
    source = Column(String(50), nullable=False, default='cmc', server_default='cmc', index=True)
    
    # --- CoinMarketCap Specific Fields ---
    cmc_id = Column(Integer, nullable=True, index=True) # Nullable because CoinGecko alerts won't have it.
    
    # --- CoinGecko Specific Fields ---
    token_address = Column(String(255), nullable=True, index=True) # e.g., 0x...
    network_id = Column(String(100), nullable=True, index=True) # e.g., 'eth', 'polygon_pos'

    # --- Common Fields ---
    token_display_name = Column(String(255), nullable=False)
    last_triggered_price = Column(Float, nullable=True)
    polling_interval_seconds = Column(Integer, nullable=True) # Custom polling interval
    # --- End Fields for Token Price Alerts ---

    # Relationships
    user = relationship("User", back_populates="alerts")

    # The alert model now has nullable foreign keys to link to a specific context
    # depending on the alert_type. This simplifies the model but requires careful
    # handling in the application logic to ensure the correct FK is used.
    # A check constraint can enforce that only one of these is non-null.
    wallet_id = Column(Integer, ForeignKey('wallets.wallet_id', ondelete='CASCADE'), nullable=True, index=True)
    tracked_wallet_id = Column(Integer, ForeignKey('tracked_wallets.tracked_wallet_id', ondelete='CASCADE'), nullable=True, index=True)
    
    # Relationships to specific alert targets
    wallet = relationship("Wallet", back_populates=None) # No back-population needed for this simple link
    tracked_wallet = relationship("TrackedWallet", back_populates=None)

    __table_args__ = (
        CheckConstraint(
            alert_type.in_(['token_price']), 
            name='check_alert_type'
        ),
        # Ensures that for 'token_price' alerts, we have either CMC data or CoinGecko data.
        CheckConstraint(
            or_(
                and_(source == 'cmc', cmc_id.isnot(None)),
                and_(source == 'coingecko', token_address.isnot(None), network_id.isnot(None))
            ),
            name='check_token_price_alert_fields'
        ),
        Index('idx_alerts_user_id_active_type', 'user_id', 'is_active', 'alert_type'),
        # Index for active CMC alerts
        Index('idx_alerts_active_cmc', 'is_active', 'source', 'cmc_id',
              postgresql_where=and_(alert_type == 'token_price', source == 'cmc')),
        # Index for active CoinGecko alerts
        Index('idx_alerts_active_coingecko', 'is_active', 'source',
              postgresql_where=and_(alert_type == 'token_price', source == 'coingecko')),
        Index('idx_alerts_cmc_id', 'cmc_id'),
        Index('idx_alerts_conditions_gin', 'conditions', postgresql_using='gin'),
    )
