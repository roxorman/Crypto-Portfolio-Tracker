-- Helper function to update the 'updated_at' timestamp
CREATE OR REPLACE FUNCTION trigger_set_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 1. Users Table (Unchanged)
CREATE TABLE users (
    user_id BIGINT PRIMARY KEY,
    username VARCHAR(255) NULL,
    first_name VARCHAR(255) NULL,
    is_premium BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    settings JSONB NULL
);
CREATE INDEX idx_users_username ON users(username);
CREATE TRIGGER set_timestamp_users BEFORE UPDATE ON users FOR EACH ROW EXECUTE PROCEDURE trigger_set_timestamp();

-- 2. Portfolios Table (Unchanged)
CREATE TABLE portfolios (
    portfolio_id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    description TEXT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, name)
);
CREATE INDEX idx_portfolios_user_id ON portfolios(user_id);
CREATE TRIGGER set_timestamp_portfolios BEFORE UPDATE ON portfolios FOR EACH ROW EXECUTE PROCEDURE trigger_set_timestamp();

-- 3. Wallets Table (User's Own Wallets - Represents Address Identity)
CREATE TABLE wallets (
    wallet_id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    address VARCHAR(255) NOT NULL,                  -- The unique wallet address string
    -- **NEW:** Type helps distinguish address formats and potential chain groups
    wallet_type VARCHAR(20) NOT NULL CHECK (wallet_type IN ('evm', 'solana', 'other')), -- Add more types as needed
    label VARCHAR(100) NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    -- **CHANGED:** User adds the address identity once.
    UNIQUE (user_id, address)
);
-- Indexes
CREATE INDEX idx_wallets_user_id ON wallets(user_id);
CREATE INDEX idx_wallets_address ON wallets(address);

-- 4. Portfolio Wallets Association Table (Links Wallet Identity + Specific Chain to Portfolio)
CREATE TABLE portfolio_wallets (
    portfolio_id INT NOT NULL REFERENCES portfolios(portfolio_id) ON DELETE CASCADE,
    wallet_id INT NOT NULL REFERENCES wallets(wallet_id) ON DELETE CASCADE,
    -- **NEW:** Specify the chain for this wallet within this portfolio context
    chain VARCHAR(50) NOT NULL,
    added_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    -- **CHANGED:** Primary key now includes chain
    PRIMARY KEY (portfolio_id, wallet_id, chain)
);
-- Indexes
CREATE INDEX idx_portfolio_wallets_portfolio_id ON portfolio_wallets(portfolio_id);
CREATE INDEX idx_portfolio_wallets_wallet_id ON portfolio_wallets(wallet_id);
-- Index to find specific chains within a portfolio/wallet combo
CREATE INDEX idx_portfolio_wallets_wallet_chain ON portfolio_wallets(wallet_id, chain);


-- 5. Tracked Wallets Table (External Wallets - Represents Address Identity)
CREATE TABLE tracked_wallets (
    tracked_wallet_id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    address VARCHAR(255) NOT NULL,
    -- **NEW:** Type helps distinguish address formats
    wallet_type VARCHAR(20) NOT NULL CHECK (wallet_type IN ('evm', 'solana', 'other')),
    label VARCHAR(100) NULL,
    alerts_enabled BOOLEAN NOT NULL DEFAULT FALSE, -- For tx alerts
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    -- **CHANGED:** User tracks the address identity once.
    UNIQUE (user_id, address)
);
-- Indexes
CREATE INDEX idx_tracked_wallets_user_id ON tracked_wallets(user_id);
CREATE INDEX idx_tracked_wallets_address ON tracked_wallets(address);


-- 6. Alerts Table (Mostly Unchanged, FK checks updated)
CREATE TABLE alerts (
    alert_id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    alert_type VARCHAR(50) NOT NULL CHECK (alert_type IN ('price', 'portfolio_value', 'wallet_tx', 'tracked_wallet_tx')),
    conditions JSONB NOT NULL,
        CONSTRAINT conditions_is_json CHECK (jsonb_typeof(conditions) = 'object'),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_triggered_at TIMESTAMP WITH TIME ZONE NULL,
    trigger_count INT NOT NULL DEFAULT 0,

    -- Nullable Foreign Keys (Link to portfolio or the wallet *identity*)
    portfolio_id INT NULL REFERENCES portfolios(portfolio_id) ON DELETE CASCADE,
    wallet_id INT NULL REFERENCES wallets(wallet_id) ON DELETE CASCADE, -- Refers to the user's wallet *identity*
    tracked_wallet_id INT NULL REFERENCES tracked_wallets(tracked_wallet_id) ON DELETE CASCADE, -- Refers to the tracked wallet *identity*

    -- **REVISED** Constraint: Wallet/Tracked alerts link to the identity table, not portfolio.
    -- Price alerts don't need FKs. Portfolio alerts link to portfolio.
    -- Wallet/Tracked TX alerts link to their respective identity tables.
    -- Chain context for TX alerts MUST be within the 'conditions' JSONB.
    CONSTRAINT check_alert_fk
        CHECK (
            (alert_type = 'portfolio_value' AND portfolio_id IS NOT NULL AND wallet_id IS NULL AND tracked_wallet_id IS NULL) OR
            (alert_type = 'wallet_tx' AND portfolio_id IS NULL AND wallet_id IS NOT NULL AND tracked_wallet_id IS NULL) OR
            (alert_type = 'tracked_wallet_tx' AND portfolio_id IS NULL AND wallet_id IS NULL AND tracked_wallet_id IS NOT NULL) OR
            (alert_type = 'price' AND portfolio_id IS NULL AND wallet_id IS NULL AND tracked_wallet_id IS NULL)
        )
);
-- Indexes (Unchanged from previous refinement)
CREATE INDEX idx_alerts_user_id ON alerts(user_id);
CREATE INDEX idx_alerts_active_type_partial ON alerts(alert_type) WHERE is_active = TRUE;
CREATE INDEX idx_alerts_conditions_gin ON alerts USING GIN (conditions jsonb_path_ops);
CREATE INDEX idx_alerts_portfolio_id ON alerts(portfolio_id) WHERE portfolio_id IS NOT NULL;
CREATE INDEX idx_alerts_wallet_id ON alerts(wallet_id) WHERE wallet_id IS NOT NULL; -- Index on the wallet identity FK
CREATE INDEX idx_alerts_tracked_wallet_id ON alerts(tracked_wallet_id) WHERE tracked_wallet_id IS NOT NULL; -- Index on the tracked wallet identity FK