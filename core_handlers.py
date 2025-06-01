# core_handlers.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from db_manager import DatabaseManager
from notifier import Notifier
import logging
from typing import Optional # Import Optional
from telegram.helpers import escape_markdown

logger = logging.getLogger(__name__)

# Callback data constants for main menu
CALLBACK_MAIN_MENU_ADD_PRICE_ALERT = "main_menu_add_price_alert"
CALLBACK_MAIN_MENU_VIEW_PORTFOLIO = "main_menu_view_portfolio" # Placeholder
CALLBACK_MAIN_MENU_WALLETS = "main_menu_wallets" # New
CALLBACK_MAIN_MENU_PORTFOLIOS = "main_menu_portfolios" # New - Placeholder for now
CALLBACK_MAIN_MENU_SETTINGS = "main_menu_settings" # Placeholder
CALLBACK_MAIN_MENU_HELP = "main_menu_help" # Placeholder

# Callback data constants for Wallet sub-menu
CALLBACK_WALLET_MENU_ADD = "wallet_menu_add"
CALLBACK_WALLET_MENU_REMOVE = "wallet_menu_remove"
CALLBACK_WALLET_MENU_LABEL = "wallet_menu_label"
CALLBACK_WALLET_MENU_LIST = "wallet_menu_list"
CALLBACK_WALLET_MENU_BACK_TO_MAIN = "wallet_menu_back_main"

# Callback data constants for Portfolio sub-menu
CALLBACK_PORTFOLIO_MENU_CREATE = "portfolio_menu_create"
CALLBACK_PORTFOLIO_MENU_LIST = "portfolio_menu_list"
CALLBACK_PORTFOLIO_MENU_DELETE = "portfolio_menu_delete"
CALLBACK_PORTFOLIO_MENU_RENAME = "portfolio_menu_rename"
CALLBACK_PORTFOLIO_MENU_ADD_WALLET = "portfolio_menu_add_wallet"
CALLBACK_PORTFOLIO_MENU_REMOVE_WALLET = "portfolio_menu_remove_wallet"
CALLBACK_PORTFOLIO_MENU_BACK_MAIN = "portfolio_menu_back_main" # Distinct back for clarity


class CoreHandlers:
    def __init__(self, db_manager: DatabaseManager, notifier: Notifier):
        self.db = db_manager
        self.notifier = notifier
        logger.info("CoreHandlers initialized.")

# core_handlers.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from db_manager import DatabaseManager
from notifier import Notifier
import logging
from typing import Optional # Import Optional
from telegram.helpers import escape_markdown

logger = logging.getLogger(__name__)

# Callback data constants for main menu
CALLBACK_MAIN_MENU_ADD_PRICE_ALERT = "main_menu_add_price_alert"
CALLBACK_MAIN_MENU_VIEW_HOLDINGS = "main_menu_view_holdings" # Renamed for clarity, will lead to sub-menu
CALLBACK_MAIN_MENU_WALLETS = "main_menu_wallets"
CALLBACK_MAIN_MENU_PORTFOLIOS = "main_menu_portfolios"
CALLBACK_MAIN_MENU_SETTINGS = "main_menu_settings" # Placeholder
CALLBACK_MAIN_MENU_HELP = "main_menu_help" # Placeholder

# Callback data constants for Wallet sub-menu
CALLBACK_WALLET_MENU_ADD = "wallet_menu_add"
CALLBACK_WALLET_MENU_REMOVE = "wallet_menu_remove"
CALLBACK_WALLET_MENU_LABEL = "wallet_menu_label"
CALLBACK_WALLET_MENU_LIST = "wallet_menu_list"
CALLBACK_WALLET_MENU_BACK_TO_MAIN = "wallet_menu_back_main"

# Callback data constants for Portfolio sub-menu
CALLBACK_PORTFOLIO_MENU_CREATE = "portfolio_menu_create"
CALLBACK_PORTFOLIO_MENU_LIST = "portfolio_menu_list"
CALLBACK_PORTFOLIO_MENU_DELETE = "portfolio_menu_delete"
CALLBACK_PORTFOLIO_MENU_RENAME = "portfolio_menu_rename"
CALLBACK_PORTFOLIO_MENU_ADD_WALLET = "portfolio_menu_add_wallet"
CALLBACK_PORTFOLIO_MENU_REMOVE_WALLET = "portfolio_menu_remove_wallet"
CALLBACK_PORTFOLIO_MENU_BACK_MAIN = "portfolio_menu_back_main" # Distinct back for clarity

# Callback data constants for View Holdings sub-menu
CALLBACK_VIEW_HOLDINGS_BACK_MAIN = "view_holdings_back_main" # New back button for this sub-menu
CALLBACK_VIEW_HOLDINGS_SELECT_PREFIX = "vh_select:" # Prefix for selecting a portfolio/wallet

class CoreHandlers:
    def __init__(self, db_manager: DatabaseManager, notifier: Notifier):
        self.db = db_manager
        self.notifier = notifier
        logger.info("CoreHandlers initialized.")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # This could also be a button in the main menu, or a separate command
        await self.notifier.send_help_message(update.effective_user.id)

    # We will add a handler for CALLBACK_MAIN_MENU_ADD_PRICE_ALERT later
    # For now, placeholder handlers for other buttons (optional)
    async def main_menu_placeholder_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        await query.message.reply_text(f"This feature ({query.data}) is coming soon!")

    # Placeholder for help button if it's different from /help command
    async def main_menu_help_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        await self.notifier.send_help_message(query.from_user.id)

    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: Optional[str] = None) -> None:
        """Reusable method to show the main menu, potentially editing a message."""
        user = update.effective_user
        if not message_text:
            message_text = (
                f"👋 Welcome back {escape_markdown(user.first_name or 'there', version=2)}\\!\n\n" # Corrected escape
                f"How can I assist you today?"
            )
        
        keyboard = [
            [InlineKeyboardButton("➕ Add Price Alert", callback_data=CALLBACK_MAIN_MENU_ADD_PRICE_ALERT)],
            [InlineKeyboardButton("📊 View Holdings", callback_data=CALLBACK_MAIN_MENU_VIEW_HOLDINGS)], # Use new constant
            [InlineKeyboardButton("💼 Wallets", callback_data=CALLBACK_MAIN_MENU_WALLETS)],
            [InlineKeyboardButton("🗂️ Portfolios", callback_data=CALLBACK_MAIN_MENU_PORTFOLIOS)],
            [InlineKeyboardButton("⚙️ Settings", callback_data=CALLBACK_MAIN_MENU_SETTINGS)],
            [InlineKeyboardButton("❓ Help", callback_data=CALLBACK_MAIN_MENU_HELP)],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query: # If called from a button press (e.g. "Back to Main Menu")
            await update.callback_query.edit_message_text(text=message_text, reply_markup=reply_markup, parse_mode='MarkdownV2')
        elif update.message: # If called from /start command
             await self.notifier.send_message(
                chat_id=user.id, 
                text=message_text, 
                reply_markup=reply_markup,
                parse_mode='MarkdownV2'
            )
    
    async def show_wallet_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Displays the wallet management sub-menu."""
        query = update.callback_query
        await query.answer()

        text = "Wallet Management Menu:"
        keyboard = [
            [InlineKeyboardButton("➕ Add Wallet", callback_data=CALLBACK_WALLET_MENU_ADD)],
            [InlineKeyboardButton("➖ Remove Wallet", callback_data=CALLBACK_WALLET_MENU_REMOVE)],
            [InlineKeyboardButton("✏️ Label Wallet", callback_data=CALLBACK_WALLET_MENU_LABEL)],
            [InlineKeyboardButton("📋 List Wallets", callback_data=CALLBACK_WALLET_MENU_LIST)],
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data=CALLBACK_WALLET_MENU_BACK_TO_MAIN)],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=text, reply_markup=reply_markup)

    async def show_portfolio_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Displays the portfolio management sub-menu."""
        query = update.callback_query
        await query.answer()

        text = "Portfolio Management Menu:"
        keyboard = [
            [InlineKeyboardButton("➕ Create Portfolio", callback_data=CALLBACK_PORTFOLIO_MENU_CREATE)],
            [InlineKeyboardButton("📋 List Portfolios", callback_data=CALLBACK_PORTFOLIO_MENU_LIST)],
            [InlineKeyboardButton("🗑️ Delete Portfolio", callback_data=CALLBACK_PORTFOLIO_MENU_DELETE)],
            [InlineKeyboardButton("✏️ Rename Portfolio", callback_data=CALLBACK_PORTFOLIO_MENU_RENAME)],
            [InlineKeyboardButton("🔗 Add Wallet to Portfolio", callback_data=CALLBACK_PORTFOLIO_MENU_ADD_WALLET)],
            [InlineKeyboardButton("➖ Remove Wallet from Portfolio", callback_data=CALLBACK_PORTFOLIO_MENU_REMOVE_WALLET)],
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data=CALLBACK_PORTFOLIO_MENU_BACK_MAIN)],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=text, reply_markup=reply_markup)

    async def back_to_main_menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles 'Back to Main Menu' button press from any sub-menu."""
        query = update.callback_query
        await query.answer()
        # Re-display the main menu by editing the current message
        await self.show_main_menu(update, context, message_text="Main Menu:")


    # Ensure the start method calls the new show_main_menu
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        db_user = await self.db.create_user(user.id, user.username, user.first_name)
        if db_user:
            logger.info(f"User {user.id} started or interacted.")
            initial_welcome_text = (
                f"👋 Welcome {escape_markdown(user.first_name or 'there', version=2)}\\!\n\n" # Corrected escape
                f"I am your Portfolio Tracking Bot\\. How can I assist you today?" # Corrected escape
            )
            await self.show_main_menu(update, context, message_text=initial_welcome_text)
        else:
            logger.error(f"Failed to create or retrieve user {user.id} in DB.")
            await update.message.reply_text("Sorry, there was an error setting up your profile. Please try again later.")
