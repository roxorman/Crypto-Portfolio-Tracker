# Crypto Portfolio Telegram Bot

A Telegram bot for tracking crypto portfolios across multiple chains, providing analytics, visualizations, and alerts.

## Features

- Multi-chain wallet tracking (Ethereum, Arbitrum, Base)
- Real-time portfolio value updates
- Token balance tracking and analytics
- Price alerts and portfolio value alerts
- Portfolio visualization (charts and graphs)
- Historical portfolio tracking
- Free and Premium tiers

## Project Structure

```
├── main.py               # Bot entry point and command handlers
├── config.py            # Configuration and environment variables
├── db_manager.py        # Database operations
├── models.py            # SQLAlchemy database models
├── wallet_manager.py    # Wallet operations and balance fetching
├── portfolio_fetcher.py # Portfolio data and analytics
├── alerts_manager.py    # Alert system management
├── notifier.py         # Telegram messaging functions
├── scheduler.py        # Scheduled tasks handler
└── utils.py           # Helper functions and utilities
```

## Setup

1. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # or
   .\venv\Scripts\activate  # Windows
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment variables:
   - Copy `.env.template` to `.env`
   - Fill in your configuration values:
     - Telegram Bot Token
     - Alchemy API Key
     - Database URL

4. Initialize the database:
   ```bash
   # Database initialization will be handled automatically on first run
   ```

5. Run the bot:
   ```bash
   python main.py
   ```

## Available Commands

- `/start` - Start using the bot
- `/addwallet` - Add a new wallet to track
- `/removewallet` - Remove a tracked wallet
- `/summary` - Get portfolio summary
- `/setalert` - Set a new alert
- `/removealert` - Remove an existing alert

## Deployment

The bot is designed to be deployed on Railway:
1. Connect your GitHub repository to Railway
2. Configure environment variables in Railway dashboard
3. Deploy the application

## Database Schema

The application uses PostgreSQL with the following main tables:
- `users` - User information and preferences
- `wallets` - Tracked wallet addresses
- `alerts` - User-configured alerts
- `portfolio_snapshots` - Historical portfolio data

## Dependencies

- python-telegram-bot - Telegram bot framework
- web3 - Ethereum interaction
- SQLAlchemy - Database ORM
- matplotlib - Chart generation
- pandas - Data analysis
- psycopg2/asyncpg - PostgreSQL adapters

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License
