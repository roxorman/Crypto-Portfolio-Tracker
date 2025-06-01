# main.py

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler, filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from config import Config
from db_manager import DatabaseManager
from wallet_manager import WalletManager # Keep for now, might be removed if not used by other parts
from api_fetcher import PortfolioFetcher
from alerts_manager import AlertsManager
from notifier import Notifier
from scheduler import Scheduler
from portfolio_analyzer import PortfolioAnalyzer

# --- NEW HANDLER IMPORTS ---
from core_handlers import (
    CoreHandlers, 
    CALLBACK_MAIN_MENU_VIEW_HOLDINGS, # Corrected import name
    CALLBACK_MAIN_MENU_SETTINGS, 
    CALLBACK_MAIN_MENU_HELP,
    CALLBACK_MAIN_MENU_WALLETS,
    CALLBACK_MAIN_MENU_PORTFOLIOS,
    CALLBACK_WALLET_MENU_LIST,
    CALLBACK_WALLET_MENU_BACK_TO_MAIN,
    CALLBACK_PORTFOLIO_MENU_LIST,
    # CALLBACK_PORTFOLIO_MENU_DELETE, # Now an entry point
    # CALLBACK_PORTFOLIO_MENU_RENAME, # Now an entry point
    # CALLBACK_PORTFOLIO_MENU_ADD_WALLET, # Now an entry point
    # CALLBACK_PORTFOLIO_MENU_REMOVE_WALLET, # Now an entry point
    CALLBACK_PORTFOLIO_MENU_BACK_MAIN,
    CALLBACK_VIEW_HOLDINGS_SELECT_PREFIX, # Added import
    CALLBACK_VIEW_HOLDINGS_BACK_MAIN # Added import
)
from wallet_management_handlers import WalletManagementHandlers
from portfolio_management_handlers import PortfolioManagementHandlers
from view_handlers import ViewHandlers
from alert_handlers import PriceAlertHandlers
# --- END NEW HANDLER IMPORTS ---

import asyncio
import signal
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

shutdown_event = asyncio.Event()

def handle_signal(sig, frame):
    print(f"Received signal {sig}, initiating shutdown...")
    try:
        loop = asyncio.get_running_loop()
        loop.call_soon_threadsafe(shutdown_event.set)
    except RuntimeError:
         print("Event loop not running, setting shutdown event directly.")
         shutdown_event.set()

def register_handlers(application, core_h, wallet_h, portfolio_h, view_h, price_alert_h):
    """Registers all command, conversation, and callback query handlers."""
    
    # Core Handlers
    application.add_handler(CommandHandler("start", core_h.start))
    application.add_handler(CommandHandler("help", core_h.help))

    # Wallet Management Conversations & Commands
    application.add_handler(WalletManagementHandlers.get_add_wallet_conversation_handler(wallet_h))
    application.add_handler(WalletManagementHandlers.get_remove_wallet_conversation_handler(wallet_h))
    application.add_handler(WalletManagementHandlers.get_label_wallet_conversation_handler(wallet_h))
    application.add_handler(CommandHandler("list", wallet_h.list_wallets))
    application.add_handler(CommandHandler("wallets", wallet_h.list_wallets)) # Alias

    # Viewing Holdings
    application.add_handler(CommandHandler("view", view_h.view_holdings))
    application.add_handler(CommandHandler("holdings", view_h.view_holdings))

    # Portfolio Management Conversations & Commands
    application.add_handler(PortfolioManagementHandlers.get_create_portfolio_conversation_handler(portfolio_h))
    application.add_handler(PortfolioManagementHandlers.get_delete_portfolio_conversation_handler(portfolio_h))
    application.add_handler(PortfolioManagementHandlers.get_rename_portfolio_conversation_handler(portfolio_h))
    application.add_handler(PortfolioManagementHandlers.get_padd_wallet_conversation_handler(portfolio_h))
    application.add_handler(PortfolioManagementHandlers.get_premove_wallet_conversation_handler(portfolio_h)) # New
    
    application.add_handler(CommandHandler("plist", portfolio_h.portfolio_list))
    # application.add_handler(CommandHandler("pcreate", portfolio_h.portfolio_create)) # Old
    # application.add_handler(CommandHandler("pdelete", portfolio_h.portfolio_delete)) # Old
    # application.add_handler(CommandHandler("prename", portfolio_h.portfolio_rename)) # Old
    # application.add_handler(CommandHandler("padd", portfolio_h.portfolio_add_wallet)) # Old
    # application.add_handler(CommandHandler("premove", portfolio_h.portfolio_remove_wallet)) # Old
    
    # Token Price Alert Conversation & Commands
    application.add_handler(PriceAlertHandlers.get_price_alert_conversation_handler(price_alert_h))
    application.add_handler(CommandHandler("alert_price_list", price_alert_h.alert_price_list))
    application.add_handler(CommandHandler("alert_price_delete", price_alert_h.alert_price_delete))

    # --- Main Menu Button Handlers ---
    application.add_handler(CallbackQueryHandler(view_h.show_view_holdings_menu, pattern=f"^{CALLBACK_MAIN_MENU_VIEW_HOLDINGS}$")) # New handler for View Holdings
    application.add_handler(CallbackQueryHandler(core_h.show_portfolio_menu, pattern=f"^{CALLBACK_MAIN_MENU_PORTFOLIOS}$"))
    application.add_handler(CallbackQueryHandler(core_h.main_menu_placeholder_callback, pattern=f"^{CALLBACK_MAIN_MENU_SETTINGS}$"))
    application.add_handler(CallbackQueryHandler(core_h.main_menu_help_callback, pattern=f"^{CALLBACK_MAIN_MENU_HELP}$"))
    
    # --- Wallet Sub-Menu Button Handlers ---
    application.add_handler(CallbackQueryHandler(core_h.show_wallet_menu, pattern=f"^{CALLBACK_MAIN_MENU_WALLETS}$"))
    application.add_handler(CallbackQueryHandler(wallet_h.list_wallets, pattern=f"^{CALLBACK_WALLET_MENU_LIST}$")) 
    application.add_handler(CallbackQueryHandler(core_h.back_to_main_menu_callback, pattern=f"^{CALLBACK_WALLET_MENU_BACK_TO_MAIN}$"))
    
    # --- Portfolio Sub-Menu Button Handlers ---
    # Create, Delete, Rename, Add Wallet, Remove Wallet are now entry points to their ConversationHandlers
    application.add_handler(CallbackQueryHandler(portfolio_h.portfolio_list, pattern=f"^{CALLBACK_PORTFOLIO_MENU_LIST}$"))
    application.add_handler(CallbackQueryHandler(core_h.back_to_main_menu_callback, pattern=f"^{CALLBACK_PORTFOLIO_MENU_BACK_MAIN}$"))

    # --- View Holdings Sub-Menu Button Handlers ---
    application.add_handler(CallbackQueryHandler(view_h.handle_view_selection, pattern=f"^{CALLBACK_VIEW_HOLDINGS_SELECT_PREFIX}"))
    application.add_handler(CallbackQueryHandler(core_h.back_to_main_menu_callback, pattern=f"^{CALLBACK_VIEW_HOLDINGS_BACK_MAIN}$"))

async def main():
    print("Initializing components...")
    try:
        config = Config()
        db = DatabaseManager(config.DATABASE_URL)
        if not db.engine:
             logger.critical("Database connection failed. Exiting.")
             return

        portfolio_fetcher = PortfolioFetcher()
        notifier = Notifier()
        if not notifier.bot:
             logger.critical("CRITICAL: Notifier failed to initialize (Invalid TELEGRAM_TOKEN?). Cannot start bot.")
             return

        logger.info("Initializing database schema...")
        await db.init_db()

        alerts_manager = AlertsManager(db_manager=db, notifier=notifier, portfolio_fetcher=portfolio_fetcher)
        portfolio_analyzer = PortfolioAnalyzer()
        wallet_manager_instance = WalletManager() # Instantiate WalletManager

        core_h = CoreHandlers(db_manager=db, notifier=notifier)
        wallet_h = WalletManagementHandlers(db_manager=db, notifier=notifier, wallet_manager=wallet_manager_instance) # Pass to constructor
        portfolio_h = PortfolioManagementHandlers(db_manager=db, notifier=notifier)
        view_h = ViewHandlers(db_manager=db, portfolio_fetcher=portfolio_fetcher, portfolio_analyzer=portfolio_analyzer, notifier=notifier)
        price_alert_h = PriceAlertHandlers(db=db, fetcher=portfolio_fetcher, notifier=notifier, wallet_manager=wallet_manager_instance) # Added wallet_manager

        application = Application.builder().token(config.TELEGRAM_TOKEN).build()

        register_handlers(application, core_h, wallet_h, portfolio_h, view_h, price_alert_h)

        print("Initializing application...")
        await application.initialize()
        print("Starting background tasks...")
        alert_check_task = asyncio.create_task(alerts_manager.check_all_alerts_loop())
        print("AlertsManager polling loop started.")
        print("Starting polling...")
        await application.start()
        await application.updater.start_polling()
        print("Bot is running. Press Ctrl+C or send SIGTERM to stop.")
        await shutdown_event.wait()
        print("Shutdown signal received. Stopping components...")

    except ValueError as e:
         logger.critical(f"Configuration error during initialization: {e}")
         print(f"CRITICAL CONFIG ERROR: {e}")
    except Exception as e:
        print(f"An error occurred during bot initialization or execution: {e}")
        logger.exception("Unhandled exception during bot execution:", exc_info=e)
    finally:
        print("Shutting down updater...")
        if 'application' in locals() and application.updater and application.updater.running:
             await application.updater.stop()
        print("Shutting down application...")
        if 'application' in locals() and application.running:
             await application.stop()
             await application.shutdown()
        print("Stopping alert check task...")
        if 'alert_check_task' in locals() and not alert_check_task.done():
            alert_check_task.cancel()
            try: await alert_check_task
            except asyncio.CancelledError: print("Alert check task cancelled.")
        print("Closing database engine...")
        if 'db' in locals() and db: await db.close_engine()
        print("Shutdown complete.")

if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    try:
        print("Starting asyncio event loop...")
        asyncio.run(main())
    except RuntimeError as e:
        if "Cannot run the event loop while another loop is running" in str(e):
             print("ERROR: Event loop conflict detected during startup.")
        else:
             print(f"RuntimeError in asyncio.run: {e}")
             logger.exception("RuntimeError during asyncio.run", exc_info=e)
    except KeyboardInterrupt:
        print("KeyboardInterrupt caught in __main__.")
    except Exception as e_main:
        print(f"Unhandled exception in top-level __main__: {e_main}")
        logger.exception("Unhandled exception in top-level __main__:", exc_info=e_main)
