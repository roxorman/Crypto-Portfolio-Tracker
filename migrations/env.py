# migrations/env.py

import os
import sys
import asyncio  # <<< Import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
# from sqlalchemy import engine_from_config # <<< No longer needed for online async
from sqlalchemy.ext.asyncio import async_engine_from_config # <<< Import async engine creator

from alembic import context
import os
from dotenv import load_dotenv

# load the .env file (assuming it's in the same directory as env.py)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

# --- Add project root to path to find models.py ---
# Adjust this path if your models.py is located elsewhere relative to the migrations directory
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from scripts.models import Base  # <<< Import your Base model from models.py
except ImportError as e:
    sys.stderr.write(f"Error: Failed to import Base from scripts/models.py. Check sys.path: {e}\n")
    sys.exit(1)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata # <<< Assign your Base.metadata here

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Include transaction_per_migration=True for broader compatibility, especially with CockroachDB
        # transaction_per_migration=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# --- Helper function needed for async online mode ---
def do_run_migrations(connection):
    """
    Helper function to be called by run_sync within the async online migration.
    Configures the context and runs the migrations.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Include transaction_per_migration=True if needed, e.g., for CockroachDB compatibility
        # transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()

# --- ASYNCHRONOUS version of run_migrations_online ---
async def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # Get the async engine configuration from alembic.ini
    # Ensure the URL uses an async driver (e.g., postgresql+asyncpg://...)
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool, # Use NullPool for migration tasks
    )

    # Connect and run migrations within the async connection context manager
    async with connectable.connect() as connection:
        # Pass the synchronous migration function to run_sync
        await connection.run_sync(do_run_migrations)

    # Dispose of the engine (important for async engines)
    await connectable.dispose()


# --- Main execution block ---
if context.is_offline_mode():
    print("Running migrations offline...")
    run_migrations_offline()
else:
    print("Running migrations online (async)...")
    # Use asyncio.run() to execute the async online migration function
    try:
        asyncio.run(run_migrations_online())
    except Exception as e:
        sys.stderr.write(f"Error running async online migrations: {e}\n")
        sys.exit(1)

print("Migrations finished.")
