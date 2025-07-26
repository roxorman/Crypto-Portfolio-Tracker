# main.py

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler, filters
from telegram import Update
from config import Config
from db_manager import DatabaseManager
from wallet_manager import WalletManager
from api_fetcher import PortfolioFetcher
from alerts_manager import AlertsManager
from notifier import Notifier
from scheduler import Scheduler
from portfolio_analyzer import PortfolioAnalyzer
from telegram.ext import ContextTypes

# --- NEW HANDLER IMPORTS ---
from core_handlers import (
    CoreHandlers, 
    CALLBACK_MAIN_MENU_VIEW_HOLDINGS,
    CALLBACK_MAIN_MENU_VIEW_PNL,
    CALLBACK_MAIN_MENU_VIEW_CHART,
    CALLBACK_MAIN_MENU_PRICE_ALERTS,
    CALLBACK_MAIN_MENU_SETTINGS, 
    CALLBACK_MAIN_MENU_HELP,
    CALLBACK_MAIN_MENU_WALLETS,
    CALLBACK_MAIN_MENU_PREMIUM, # Added
    CALLBACK_MAIN_MENU_WALLET_TRANSACTION_ANALYZER,
    CALLBACK_PREMIUM_PLAN_PREFIX, # Added
    CALLBACK_PAY_CRYPTO_PREFIX, # Added
    CALLBACK_BACK_TO_PREMIUM_PLANS, # Added
    CALLBACK_BACK_TO_PAYMENT_OPTIONS_PREFIX, # Added
    CALLBACK_WALLET_MENU_LIST,
    CALLBACK_WALLET_MENU_BACK_TO_MAIN,
    CALLBACK_WALLET_MENU_REMOVE,
    CALLBACK_VIEW_HOLDINGS_SELECT_PREFIX,
    CALLBACK_VIEW_HOLDINGS_BACK_MAIN,
    CALLBACK_ALERTS_MENU_ADD,
    CALLBACK_ALERTS_MENU_VIEW,
    CALLBACK_ALERTS_MENU_DELETE,
    CALLBACK_ALERTS_MENU_BACK_TO_MAIN
)
from wallet_management_handlers import WalletManagementHandlers, CALLBACK_REMOVE_WALLET_PREFIX
from view_handlers import ViewHandlers, CALLBACK_SELECT_VIEW_TYPE_PREFIX
from alert_handlers import PriceAlertHandlers, CALLBACK_DELETE_ALERT_PREFIX, CALLBACK_BACK_TO_ALERTS_MENU
from wallet_chart_handlers import WalletChartHandlers, CALLBACK_WALLET_CHART_MENU_BACK_MAIN, CALLBACK_WALLET_CHART_SELECT_PREFIX, CALLBACK_WALLET_CHART_PERIOD_PREFIX
from transaction_analyzer_handlers import TransactionAnalyzerHandlers, CALLBACK_ANALYZE_WALLET_PREFIX, CALLBACK_ANALYZE_SENT_PREFIX, CALLBACK_ANALYZE_RECEIVED_PREFIX, CALLBACK_ANALYZE_EXECUTE_PREFIX
# --- END NEW HANDLER IMPORTS ---

import asyncio
import signal
import logging

# ... (logging setup and shutdown handling remain the same) ...
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

def register_handlers(application, core_h, wallet_h, view_h, price_alert_h, wallet_chart_h, transaction_analyzer_h):
    logger.info("Registering handlers...")
    
    # Core Handlers
    application.add_handler(CommandHandler("start", core_h.start))
    application.add_handler(CommandHandler("help", core_h.help))
    application.add_handler(CommandHandler("seeusers", core_h.see_users))

    # Wallet Management Conversations
    application.add_handler(WalletManagementHandlers.get_add_wallet_conversation_handler(wallet_h))
    application.add_handler(WalletManagementHandlers.get_label_wallet_conversation_handler(wallet_h))
    
    # Price Alert Conversation
    application.add_handler(PriceAlertHandlers.get_price_alert_conversation_handler(price_alert_h))

    # Command Shortcuts
    application.add_handler(CommandHandler("view", view_h.view_holdings))
    application.add_handler(CommandHandler("pnl", view_h.view_pnl_stats))
    application.add_handler(CommandHandler("wallets", wallet_h.list_wallets))
    application.add_handler(CommandHandler("alert_price_list", price_alert_h.alert_price_list))
    application.add_handler(CommandHandler("alert_price_delete", price_alert_h.alert_price_delete))

    # --- Main Menu Button Handlers ---
    application.add_handler(CallbackQueryHandler(view_h.show_view_holdings_menu, pattern=f"^{CALLBACK_MAIN_MENU_VIEW_HOLDINGS}$"))
    application.add_handler(CallbackQueryHandler(view_h.handle_pnl_button, pattern=f"^{CALLBACK_MAIN_MENU_VIEW_PNL}$"))
    application.add_handler(CallbackQueryHandler(wallet_chart_h.show_wallet_chart_menu, pattern=f"^{CALLBACK_MAIN_MENU_VIEW_CHART}$"))
    application.add_handler(CallbackQueryHandler(core_h.show_price_alerts_menu, pattern=f"^{CALLBACK_MAIN_MENU_PRICE_ALERTS}$"))
    application.add_handler(CallbackQueryHandler(core_h.show_wallet_menu, pattern=f"^{CALLBACK_MAIN_MENU_WALLETS}$"))
    # --- PREMIUM FLOW HANDLERS ---
    application.add_handler(CallbackQueryHandler(core_h.show_premium_plans, pattern=f"^{CALLBACK_MAIN_MENU_PREMIUM}$"))
    application.add_handler(CallbackQueryHandler(core_h.show_payment_options, pattern=f"^{CALLBACK_PREMIUM_PLAN_PREFIX}"))
    application.add_handler(CallbackQueryHandler(core_h.show_crypto_payment_info, pattern=f"^{CALLBACK_PAY_CRYPTO_PREFIX}"))
    application.add_handler(CallbackQueryHandler(core_h.show_premium_plans, pattern=f"^{CALLBACK_BACK_TO_PREMIUM_PLANS}$"))
    application.add_handler(CallbackQueryHandler(core_h.show_payment_options, pattern=f"^{CALLBACK_BACK_TO_PAYMENT_OPTIONS_PREFIX}"))
    
    # --- END PREMIUM FLOW HANDLERS ---
    application.add_handler(CallbackQueryHandler(transaction_analyzer_h.transaction_analyzer_menu, pattern=f"^{CALLBACK_MAIN_MENU_WALLET_TRANSACTION_ANALYZER}$"))
    application.add_handler(CallbackQueryHandler(transaction_analyzer_h.select_transaction_type_menu, pattern=f"^{CALLBACK_ANALYZE_WALLET_PREFIX}"))
    
    # These two now point to the timeframe selection menu
    application.add_handler(CallbackQueryHandler(transaction_analyzer_h.select_timeframe_menu, pattern=f"^{CALLBACK_ANALYZE_SENT_PREFIX}"))
    application.add_handler(CallbackQueryHandler(transaction_analyzer_h.select_timeframe_menu, pattern=f"^{CALLBACK_ANALYZE_RECEIVED_PREFIX}"))
    # This new handler executes the final analysis
    application.add_handler(CallbackQueryHandler(transaction_analyzer_h.analyze_wallet_transactions, pattern=f"^{CALLBACK_ANALYZE_EXECUTE_PREFIX}"))

    # --- Core Handlers ---
    application.add_handler(CallbackQueryHandler(core_h.main_menu_placeholder_callback, pattern=f"^{CALLBACK_MAIN_MENU_SETTINGS}$"))
    application.add_handler(CallbackQueryHandler(core_h.main_menu_help_callback, pattern=f"^{CALLBACK_MAIN_MENU_HELP}$"))
    
    # --- Price Alerts Sub-Menu Handlers ---
    application.add_handler(CallbackQueryHandler(price_alert_h.alert_price_list, pattern=f"^{CALLBACK_ALERTS_MENU_VIEW}$"))
    application.add_handler(CallbackQueryHandler(price_alert_h.delete_alert_start, pattern=f"^{CALLBACK_ALERTS_MENU_DELETE}$"))
    application.add_handler(CallbackQueryHandler(price_alert_h.handle_delete_alert_selection, pattern=f"^{CALLBACK_DELETE_ALERT_PREFIX}"))
    application.add_handler(CallbackQueryHandler(core_h.show_price_alerts_menu, pattern=f"^{CALLBACK_BACK_TO_ALERTS_MENU}$"))
    application.add_handler(CallbackQueryHandler(core_h.back_to_main_menu_callback, pattern=f"^{CALLBACK_ALERTS_MENU_BACK_TO_MAIN}$"))
    application.add_handler(CallbackQueryHandler(price_alert_h.start_price_alert_conversation, pattern=f"^{CALLBACK_ALERTS_MENU_ADD}$"))
    
    # --- Wallet Sub-Menu Handlers ---
    # Note: ADD and LABEL are handled by their ConversationHandlers
    application.add_handler(CallbackQueryHandler(wallet_h.remove_wallet_start, pattern=f"^{CALLBACK_WALLET_MENU_REMOVE}$"))
    application.add_handler(CallbackQueryHandler(wallet_h.handle_remove_wallet_selection, pattern=f"^{CALLBACK_REMOVE_WALLET_PREFIX}"))
    application.add_handler(CallbackQueryHandler(wallet_h.list_wallets, pattern=f"^{CALLBACK_WALLET_MENU_LIST}$")) 
    application.add_handler(CallbackQueryHandler(core_h.back_to_main_menu_callback, pattern=f"^{CALLBACK_WALLET_MENU_BACK_TO_MAIN}$"))
    
    # --- View/Chart Sub-Menu Handlers ---
    application.add_handler(CallbackQueryHandler(view_h.handle_pnl_wallet_selection, pattern=f"^pnl_wallet:"))
    application.add_handler(CallbackQueryHandler(view_h.handle_view_type_selection, pattern=f"^{CALLBACK_SELECT_VIEW_TYPE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(view_h.handle_view_selection, pattern=f"^{CALLBACK_VIEW_HOLDINGS_SELECT_PREFIX}"))
    application.add_handler(CallbackQueryHandler(core_h.back_to_main_menu_callback, pattern=f"^{CALLBACK_VIEW_HOLDINGS_BACK_MAIN}$"))
    application.add_handler(CallbackQueryHandler(wallet_chart_h.handle_wallet_selection, pattern=f"^{CALLBACK_WALLET_CHART_SELECT_PREFIX}"))
    application.add_handler(CallbackQueryHandler(wallet_chart_h.handle_period_selection, pattern=f"^{CALLBACK_WALLET_CHART_PERIOD_PREFIX}"))
    application.add_handler(CallbackQueryHandler(core_h.back_to_main_menu_callback, pattern=f"^{CALLBACK_WALLET_CHART_MENU_BACK_MAIN}$"))
    application.add_handler(CallbackQueryHandler(wallet_chart_h.show_wallet_chart_menu, pattern=f"^wallet_chart_back_to_wallets$"))
    application.add_handler(CallbackQueryHandler(wallet_chart_h.handle_wallet_selection, pattern=f"^wallet_chart_back_to_periods$"))

# ... (main function and startup logic remain the same) ...
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
        wallet_manager_instance = WalletManager()
        
        core_h = CoreHandlers(db_manager=db, notifier=notifier, config=config)
        wallet_h = WalletManagementHandlers(db_manager=db, notifier=notifier, wallet_manager=wallet_manager_instance, config=config, core_handlers=core_h)
        view_h = ViewHandlers(db_manager=db, portfolio_fetcher=portfolio_fetcher, portfolio_analyzer=portfolio_analyzer, notifier=notifier, config=config)
        price_alert_h = PriceAlertHandlers(db=db, fetcher=portfolio_fetcher, notifier=notifier, wallet_manager=wallet_manager_instance, config=config, core_handlers=core_h)
        wallet_chart_h = WalletChartHandlers(db_manager=db, portfolio_fetcher=portfolio_fetcher, notifier=notifier, config=config)
        transaction_analyzer_h = TransactionAnalyzerHandlers(db_manager=db, config=config, portfolio_fetcher=portfolio_fetcher)

        application = Application.builder().token(config.TELEGRAM_TOKEN).build()

        register_handlers(application, core_h, wallet_h, view_h, price_alert_h, wallet_chart_h, transaction_analyzer_h)

        async def set_premium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            """Grants or revokes premium status to a user. Admin only."""
            if update.effective_user.id not in config.ADMIN_USER_IDS:
                logger.warning(f"Non-admin user {update.effective_user.id} tried to use /setpremium")
                await update.message.reply_text("You are not authorized to use this command.")
                return

            try:
                if len(context.args) < 2:
                    await update.message.reply_text("Usage: /setpremium <user_id> <true/false> [days]")
                    return
                
                target_user_id = int(context.args[0])
                status_str = context.args[1].lower()
                days = int(context.args[2]) if len(context.args) > 2 else None

                if status_str not in ['true', 'false']:
                    await update.message.reply_text("Invalid status. Use 'true' or 'false'.")
                    return
                
                is_premium = status_str == 'true'
                
                user = await db.set_user_premium_status(target_user_id, is_premium=is_premium, days=days)

                if user:
                    status_text = "granted" if is_premium else "revoked"
                    if is_premium and days:
                        await update.message.reply_text(f"✅ User {target_user_id}'s premium status has been set to {is_premium} for {days} days.")
                    else:
                        await update.message.reply_text(f"✅ User {target_user_id}'s premium status has been set to {is_premium}.")
                    
                    # Notify the user
                    if is_premium:
                        if days:
                            user_message = f"💎 Your account has been upgraded to Premium for {days} days! Enjoy the benefits."
                        else:
                            user_message = f"💎 Your account has been upgraded to Premium! Enjoy the benefits."
                    else:
                        user_message = "Your Premium status has been revoked. Please contact an admin if you believe this is an error."
                    await notifier.send_message(target_user_id, user_message)
                else:
                    await update.message.reply_text(f"❌ User {target_user_id} not found.")

            except (IndexError, ValueError):
                await update.message.reply_text("Usage: /setpremium <user_id> <true/false> [days]")
            except Exception as e:
                logger.error(f"Error in /setpremium handler: {e}")
                await update.message.reply_text("An error occurred while processing the command.")

        application.add_handler(CommandHandler("setpremium", set_premium))

        print("Initializing application...")
        await application.initialize()
        
        print("Starting background tasks...")
        scheduler = Scheduler(db_manager=db, notifier=notifier)
        cmc_alert_task = asyncio.create_task(alerts_manager.check_cmc_alerts_loop())
        coingecko_alert_task = asyncio.create_task(alerts_manager.check_coingecko_alerts_loop())
        premium_check_task = asyncio.create_task(scheduler.check_premium_expirations_loop())
        background_tasks = [cmc_alert_task, coingecko_alert_task, premium_check_task]
        print("AlertsManager and Scheduler polling loops started.")

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
        
        print("Stopping background tasks...")
        if 'background_tasks' in locals():
            for task in background_tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass # Expected
        print("Background tasks stopped.")

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
