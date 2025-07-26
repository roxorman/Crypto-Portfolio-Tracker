# Crypto Portfolio Telegram Bot

A Telegram bot for tracking crypto portfolios across multiple chains, providing analytics, visualizations, and alerts.

## Core Features

- **Multi-Chain Portfolio Tracking**: View detailed holdings for any EVM-compatible wallet, powered by the Zerion API.
- **Detailed Portfolio Analysis**: Choose between a high-level summary view (total value, 24h change, distribution by chain) and a detailed view of your top 100 token positions.
- **Profit & Loss (PnL) Insights**: Analyze your wallet's performance with realized/unrealized gains and fee data.
- **Historical Value Charting**: Generate historical value charts for your wallets over various time periods (Day, Week, Month, Year, Max).
- **Custom Price Alerts**: Set up alerts for when a token's price goes above or below a target, using data from CoinMarketCap and CoinGecko.
- **Free and Premium Tiers**: Access basic features for free or upgrade to premium for higher limits on wallets and alerts.

## Project Structure

The project is organized with all main application logic located within the `scripts/` directory.

```
.
├── Dockerfile              # Instructions for building the application container for deployment.
├── railway.json            # Railway-specific deployment configuration.
├── requirements.txt        # A list of all Python dependencies for the project.
├── alembic.ini             # Configuration for Alembic database migrations.
├── migrations/             # Contains database migration scripts managed by Alembic.
├── resources/              # Static resources like the help text.
└── scripts/                # Main source code for the bot.
    ├── main.py             # Bot entry point, initializes and runs the application.
    ├── config.py           # Handles environment variables and configuration.
    ├── db_manager.py       # Manages all database interactions using SQLAlchemy.
    ├── models.py           # Defines the database schema with SQLAlchemy models.
    ├── api_fetcher.py      # Fetches data from external APIs (Zerion, CMC, etc.).
    ├── *_handlers.py       # Modules for handling different bot features (wallets, alerts, views).
    └── ...                 # Other utility and manager scripts.
```

## Local Setup

1.  **Create a virtual environment**:
    ```bash
    python -m venv venv_pftracker
    source venv_pftracker/bin/activate  # Linux/Mac
    # or
    .\venv_pftracker\Scripts\activate  # Windows
    ```

2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure environment variables**:
    -   Create a file named `.env`.
    -   Fill in your secret keys and tokens (`TELEGRAM_TOKEN`, `DATABASE_URL`, API keys).

4.  **Run database migrations**:
    ```bash
    alembic upgrade head
    ```

5.  **Run the bot**:
    ```bash
    python scripts/main.py
    ```

## Usage

The bot is primarily operated through an interactive, button-based menu.

-   **`/start`**: Initializes the bot and displays the main menu.
-   From the menu, you can navigate to manage wallets, view holdings, set price alerts, and more.

## Deployment on Railway

This project is pre-configured for easy deployment on Railway.

1.  Push the entire project repository to GitHub.
2.  Create a new project on Railway and link it to your GitHub repository.
3.  Add a PostgreSQL database service in your Railway project.
4.  Configure your environment variables (e.g., `TELEGRAM_TOKEN`, `DATABASE_URL`) in the Railway service settings.

Railway will automatically use the `Dockerfile` to build the image and the `railway.json` file to run database migrations (`alembic upgrade head`) before starting the bot.

## Dependencies

-   **python-telegram-bot**: The core framework for the Telegram bot.
-   **SQLAlchemy**: ORM for database interaction.
-   **Alembic**: Handles database migrations.
-   **aiohttp**: For asynchronous API requests.
-   **psycopg2-binary / asyncpg**: PostgreSQL database adapters.
-   **matplotlib**: Used for generating wallet charts.
