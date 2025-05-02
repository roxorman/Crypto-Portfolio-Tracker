# main.py

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler, filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from config import Config
from db_manager import DatabaseManager
from wallet_manager import WalletManager
from api_fetcher import PortfolioFetcher
from alerts_manager import AlertsManager
from notifier import Notifier
from scheduler import Scheduler
from bot_handlers import BotHandlers
from portfolio_analyzer import PortfolioAnalyzer # Import PortfolioAnalyzer
import asyncio
import signal # Import signal module for handling termination
import logging

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Global variable to signal shutdown ---
shutdown_event = asyncio.Event()

def handle_signal(sig, frame):
    """Signal handler to trigger graceful shutdown."""
    print(f"Received signal {sig}, initiating shutdown...")
    asyncio.create_task(trigger_shutdown())

async def trigger_shutdown():
    """Sets the shutdown event."""
    shutdown_event.set()

async def main():
    """Main function to initialize and start the bot."""
    print("Initializing components...")
    # Initialize components
    config = Config()
    db = DatabaseManager(config.DATABASE_URL)
    if not db.engine: # Check if DB connection failed in __init__
         logger.critical("Database connection failed. Exiting.")
         return
    
    wallet_manager = WalletManager()
    portfolio_fetcher = PortfolioFetcher()
    notifier = Notifier() # Instantiate Notifier ONCE here

    # Check if Notifier initialized correctly
    if not notifier.bot:
         print("CRITICAL: Notifier failed to initialize. Cannot start bot.")
         return # Exit if bot token is invalid

    # Initialize database
    logger.info("Initializing database schema...")
    await db.init_db()

    
    alerts_manager = AlertsManager(
        db_manager=db,
        notifier=notifier, # Pass the single Notifier instance
        portfolio_fetcher=portfolio_fetcher
    )

    # Initialize scheduler with dependencies
    # --- Make sure Scheduler __init__ doesn't create its own Notifier ---
    scheduler = Scheduler(
        db_manager=db,
        portfolio_fetcher=portfolio_fetcher,
        alerts_manager=alerts_manager,
        notifier=notifier # Pass the single Notifier instance
    )

    # Initialize portfolio analyzer
    portfolio_analyzer = PortfolioAnalyzer() # Instantiate PortfolioAnalyzer

    # Initialize bot handlers
    # --- Make sure BotHandlers __init__ doesn't create its own Notifier ---
    handlers = BotHandlers(
        db_manager=db,
        wallet_manager=wallet_manager,
        portfolio_fetcher=portfolio_fetcher,
        alerts_manager=alerts_manager,
        notifier=notifier, # Pass the single Notifier instance
        scheduler=scheduler,
        portfolio_analyzer=portfolio_analyzer # Pass the PortfolioAnalyzer instance
    )

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(config.TELEGRAM_TOKEN).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("help", handlers.help))

    # --- Portfolio Commands ---
    application.add_handler(CommandHandler("portfolio_create", handlers.portfolio_create))
    application.add_handler(CommandHandler("portfolio_list", handlers.portfolio_list))
    application.add_handler(CommandHandler("portfolio_delete", handlers.portfolio_delete))
    application.add_handler(CommandHandler("portfolio_rename", handlers.portfolio_rename))
    application.add_handler(CommandHandler("portfolio_add_wallet", handlers.portfolio_add_wallet)) # Changed from p_add
    application.add_handler(CommandHandler("portfolio_remove_wallet", handlers.portfolio_remove_wallet)) # Changed from p_remove
    application.add_handler(CommandHandler("portfolio_holdings", handlers.portfolio_holdings)) # Added holdings command
    # ^^^^^^^^^^^^ MODIFIED COMMAND NAMES ^^^^^^^^^^^^
    # TODO: Add other handlers for Wallet, Analytics, Alerts, Trackers, Settings
    
    # --- Application Lifecycle Management ---
    try:
        print("Initializing application...")
        await application.initialize() # Initialize handlers, bot instance, etc.
        print("Starting background tasks...")
        # --- Start Alert Checking Task (Moved from Scheduler start for simplicity now) ---
        # It's better in Scheduler long-term, but AlertsManager doesn't depend on Scheduler to start checks
        alert_check_task = asyncio.create_task(alerts_manager.check_all_alerts())
        print("Alert checker started.")
        # scheduler_task = asyncio.create_task(scheduler.start()) # Start scheduler (Optional for now if only alerts needed)
        # print("Scheduler started.")
        print("Starting polling...")
        await application.start() # Connect to Telegram but doesn't block like run_polling
        await application.updater.start_polling() # Start the background polling

        print("Bot is running. Press Ctrl+C to stop.")

        # Keep the main function running until shutdown is signaled
        await shutdown_event.wait()

        print("Shutdown signal received. Stopping components...")

    except Exception as e:
        print(f"An error occurred during bot execution: {e}")
        logger.exception("Unhandled exception during bot execution:", exc_info=e) # Log traceback
    finally:
        print("Shutting down updater...")
        if application.updater and application.updater.running:
             await application.updater.stop()
        print("Shutting down application...")
        if application.running:
             await application.stop()
             await application.shutdown() # Ensure proper cleanup
        print("Stopping alert check task...")
        if 'alert_check_task' in locals() and not alert_check_task.done():
            alert_check_task.cancel()
            try:
                await alert_check_task # Allow cancellation to propagate
            except asyncio.CancelledError:
                print("Alert check task cancelled.")
        # print("Stopping scheduler task...") # Uncomment if scheduler is used
        # if 'scheduler_task' in locals() and not scheduler_task.done():
        #      scheduler_task.cancel()
        #      try:
        #          await scheduler_task # Allow cancellation to propagate
        #      except asyncio.CancelledError:
        #          print("Scheduler task cancelled.")
        print("Closing database engine...")
        if db:
             await db.close_engine() # Add a close_engine method to DbManager
        print("Shutdown complete.")

# Run the main function
if __name__ == "__main__":
    # --- Setup signal handlers for graceful shutdown ---
    # SIGINT is Ctrl+C
    signal.signal(signal.SIGINT, handle_signal)
    # SIGTERM is sent by process managers like systemd or Docker
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        print("Starting asyncio event loop...")
        asyncio.run(main())
    except RuntimeError as e:
        # Catch the specific error if it still happens during initial loop start
        if "Cannot run the event loop while another loop is running" in str(e):
             print("ERROR: Event loop conflict detected during startup.")
        else:
             print(f"RuntimeError in asyncio.run: {e}")
    except KeyboardInterrupt:
        # This might not be reached if signals are handled, but good fallback
        print("KeyboardInterrupt caught in __main__.")
    except Exception as e_main:
        print(f"Unhandled exception in __main__: {e_main}")
        logger.exception("Unhandled exception in top-level __main__:", exc_info=e_main) # Log traceback
