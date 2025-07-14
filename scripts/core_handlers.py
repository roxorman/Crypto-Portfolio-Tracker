from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from db_manager import DatabaseManager
from config import Config
from notifier import Notifier
import logging
from typing import Optional
from datetime import datetime, timezone, timedelta
from telegram.helpers import escape_markdown


logger = logging.getLogger(__name__)

# Callback data constants for main menu
CALLBACK_MAIN_MENU_VIEW_HOLDINGS = "main_menu_view_holdings"
CALLBACK_MAIN_MENU_VIEW_PNL = "main_menu_view_pnl"
CALLBACK_MAIN_MENU_VIEW_CHART = "main_menu_view_chart"
CALLBACK_MAIN_MENU_WALLETS = "main_menu_wallets"
CALLBACK_MAIN_MENU_PRICE_ALERTS = "main_menu_price_alerts" # New constant
CALLBACK_MAIN_MENU_SETTINGS = "main_menu_settings"
CALLBACK_MAIN_MENU_HELP = "main_menu_help"
CALLBACK_MAIN_MENU_PREMIUM = "main_menu_premium"
CALLBACK_MAIN_MENU_WALLET_TRANSACTION_ANALYZER = "main_menu_wallet_transaction_analyzer"

# Callback data constants for Wallet sub-menu
CALLBACK_WALLET_MENU_ADD = "wallet_menu_add"
CALLBACK_WALLET_MENU_REMOVE = "wallet_menu_remove"
CALLBACK_WALLET_MENU_LABEL = "wallet_menu_label"
CALLBACK_WALLET_MENU_LIST = "wallet_menu_list"
CALLBACK_WALLET_MENU_BACK_TO_MAIN = "wallet_menu_back_main"

# Callback data constants for View Holdings sub-menu
CALLBACK_VIEW_HOLDINGS_BACK_MAIN = "view_holdings_back_main"
CALLBACK_VIEW_HOLDINGS_SELECT_PREFIX = "vh_select:"

# Callback data constants for Price Alerts sub-menu
CALLBACK_ALERTS_MENU_ADD = "alerts_menu_add"
CALLBACK_ALERTS_MENU_VIEW = "alerts_menu_view"
CALLBACK_ALERTS_MENU_DELETE = "alerts_menu_delete"
CALLBACK_ALERTS_MENU_BACK_TO_MAIN = "alerts_menu_back_main"

# --- NEW: Premium Flow Callback Constants ---
CALLBACK_PREMIUM_PLAN_PREFIX = "premium_plan:"
CALLBACK_PAY_CRYPTO_PREFIX = "pay_crypto:"
CALLBACK_BACK_TO_PREMIUM_PLANS = "back_to_premium_plans"
CALLBACK_BACK_TO_PAYMENT_OPTIONS_PREFIX = "back_to_payment_options:"

class CoreHandlers:
    def __init__(self, db_manager: DatabaseManager, notifier: Notifier, config: Config):
        self.db = db_manager
        self.notifier = notifier
        self.config = config
        self.premium_plans = {
            1: {"price": 10, "name": "1 Month"},
            6: {"price": 55, "name": "6 Months"},
            12: {"price": 90, "name": "1 Year"}
        }
        logger.info("CoreHandlers initialized.")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.notifier.send_help_message(update.effective_user.id)

    async def main_menu_placeholder_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        logger.info(f"main_menu_placeholder_callback called with callback data: {query.data}")
        await query.answer()
        await query.message.reply_text(f"This feature ({query.data}) is coming soon!")

    async def main_menu_help_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        await self.notifier.send_help_message(query.from_user.id)

    async def show_premium_plans(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Displays the premium subscription plans."""
        query = update.callback_query
        await query.answer()
        
        message_text = (
            "🌟 *Unlock Premium Features\\!* 🌟\n\n"
            "Upgrade to Premium to get the best experience:\n"
            "✅ Up to 10 active price alerts\n"
            "✅ Add up to 10 wallets\n"
            "✅ 30 data requests per day\n"
            "✅ Priority support\n\n"
            "Choose your plan below:"
        )
        
        keyboard = [
            [InlineKeyboardButton(f"1 Month - ${self.premium_plans[1]['price']}", callback_data=f"{CALLBACK_PREMIUM_PLAN_PREFIX}1")],
            [InlineKeyboardButton(f"6 Months - ${self.premium_plans[6]['price']}", callback_data=f"{CALLBACK_PREMIUM_PLAN_PREFIX}6")],
            [InlineKeyboardButton(f"1 Year - ${self.premium_plans[12]['price']}", callback_data=f"{CALLBACK_PREMIUM_PLAN_PREFIX}12")],
            [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_WALLET_MENU_BACK_TO_MAIN)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text=message_text, reply_markup=reply_markup, parse_mode='MarkdownV2')

    async def show_payment_options(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Shows payment options for a selected premium plan."""
        query = update.callback_query
        await query.answer()

        try:
            months = int(query.data.split(':')[1])
            plan = self.premium_plans[months]
        except (ValueError, IndexError, KeyError):
            await query.edit_message_text("Invalid plan selected. Please try again.")
            return
            
        message_text = (
            f"You've selected the *{plan['name']}* plan for *${plan['price']}*\\.\n\n"
            "Please choose your payment method\\. For crypto payments, you will need to "
            "contact the admin directly after sending the funds\\."
        )

        keyboard = [
            [InlineKeyboardButton("💳 Pay with Stripe", url="https://buy.stripe.com/YOUR_LINK_HERE")], # Placeholder URL
            [InlineKeyboardButton("🦄 Pay with Crypto (EVM)", callback_data=f"{CALLBACK_PAY_CRYPTO_PREFIX}evm:{months}")],
            [InlineKeyboardButton("SOL Pay with Crypto (Solana)", callback_data=f"{CALLBACK_PAY_CRYPTO_PREFIX}sol:{months}")],
            [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_TO_PREMIUM_PLANS)],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=message_text, reply_markup=reply_markup, parse_mode='MarkdownV2')

    async def show_crypto_payment_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Shows instructions for paying with crypto."""
        query = update.callback_query
        await query.answer()

        try:
            _, crypto_type, months_str = query.data.split(':')
            months = int(months_str)
            plan = self.premium_plans[months]
            price = plan['price']
        except (ValueError, IndexError, KeyError):
            await query.edit_message_text("Invalid selection. Please try again.")
            return

        admin_handle = "roxor97" # Admin username
        message_text = ""
        
        if crypto_type == 'evm':
            address = "0xCe100d94EA22aAb119633D434BdEEA26F4244d1a"
            message_text = (
                f"Please send the equivalent of *${price}* in crypto to the following address on the *Base, BNB, or Linea network*\\.\n\n"
                f"Address:\n`{address}`\n_\\(Tap address to copy\\)_\n\n"
                f"*IMPORTANT*: After sending, please DM the admin *@{admin_handle}* with your transaction ID to get your premium access\\."
            )
        elif crypto_type == 'sol':
            address = "DXm7q65Grad9fAkWVkVCDwt1RJX1ARkntH964cS1FdYd"
            message_text = (
                f"Please send the equivalent of *${price}* in SOL or SPL tokens to the following address\\.\n\n"
                f"Address:\n`{address}`\n_\\(Tap address to copy\\)_\n\n"
                f"*IMPORTANT*: After sending, please DM the admin *@{admin_handle}* with your transaction ID to get your premium access\\."
            )
        
        # The back button needs to re-trigger the show_payment_options handler with the correct plan
        back_callback_data = f"{CALLBACK_PREMIUM_PLAN_PREFIX}{months}"
        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data=back_callback_data)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text=message_text, reply_markup=reply_markup, parse_mode='MarkdownV2')

    async def see_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Lists all users sorted by last activity. Admin only."""
        user_id = update.effective_user.id
        if user_id not in self.config.ADMIN_USER_IDS:
            logger.warning(f"Non-admin user {user_id} tried to use /seeusers")
            return

        users = await self.db.get_all_users_by_activity()

        if not users:
            await update.message.reply_text("No users found in the database.")
            return

        message_lines = []
        now = datetime.now(timezone.utc)
        one_week_ago = now - timedelta(days=7)
        active_in_week = 0

        for user in users:
            # Determine last active time
            last_active = user.updated_at
            user_id = user.user_id
            if user.last_api_call_at and user.last_api_call_at > last_active:
                last_active = user.last_api_call_at

            # Count users active in the past week
            if last_active >= one_week_ago:
                active_in_week += 1

            time_since = now - last_active
            is_premium = " (Premium)" if user.is_premium else "Free"
            
            # Human-readable time since
            if time_since.days > 0:
                time_ago = f"{time_since.days}d ago"
            elif (seconds := time_since.total_seconds()) > 3600:
                time_ago = f"{int(seconds // 3600)}h ago"
            elif seconds > 60:
                time_ago = f"{int(seconds // 60)}m ago"
            else:
                time_ago = f"{int(seconds)}s ago"

            user_display = user.first_name or f"User"
            if user.username:
                user_display += f" (@{user.username})"
            else:
                user_display += f" ID: {user.user_id}"
            
            safe_user_display = escape_markdown(user_display, version=2)
            last_active_str = last_active.strftime('%Y-%m-%d %H:%M')
            
            line = (
                f"\\- {safe_user_display} \\(ID: {user.user_id}\\)\n"
                f"  *Status*: `{is_premium}`\n"
                f"  *Last Active*: `{last_active_str} UTC` \\({time_ago}\\)"
            )
            message_lines.append(line)

        # Send messages in chunks of 15 users at a time to be safe
        for i in range(0, len(message_lines), 20):
            chunk = message_lines[i:i + 20]
            header = f"*Your Active Users \\(Total: {len(users)}, Active in past week: {active_in_week}\\):*\n\n" if i == 0 else ""
            message_text = header + "\n\n".join(chunk)
            await update.message.reply_text(message_text, parse_mode='MarkdownV2')

    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: Optional[str] = None, is_new_user: bool = False) -> None:
        user = update.effective_user
        logger.info(f"Showing main menu to user {user.id}")

        if is_new_user:
            message_text = (
                f"👋 Welcome {escape_markdown(user.first_name or 'there', version=2)}\\!\n\n"
                "To get started, please click on the *Wallets* button below and add your crypto wallet address to the bot\\."
            )
            wallets_button_text = "💼 Wallets (Start Here!) ➡️"
        else:
            if not message_text:
                message_text = f"👋 Welcome back {escape_markdown(user.first_name or 'there', version=2)}\\!\n\nHow can I assist you today?"
            wallets_button_text = "💼 Wallets       ➡️"

        keyboard = [
            [InlineKeyboardButton("📊 View Holdings ➡️", callback_data=CALLBACK_MAIN_MENU_VIEW_HOLDINGS)],
            [InlineKeyboardButton("💹 View PnL      ➡️", callback_data=CALLBACK_MAIN_MENU_VIEW_PNL)],
            [InlineKeyboardButton("📈 Wallet Chart  ➡️", callback_data=CALLBACK_MAIN_MENU_VIEW_CHART)],
            [InlineKeyboardButton("🚨 Price Alerts  ➡️", callback_data=CALLBACK_MAIN_MENU_PRICE_ALERTS)],
            [InlineKeyboardButton(wallets_button_text, callback_data=CALLBACK_MAIN_MENU_WALLETS)],
            [InlineKeyboardButton("💳 Wallet Transaction Analyzer", callback_data=CALLBACK_MAIN_MENU_WALLET_TRANSACTION_ANALYZER)],
            [InlineKeyboardButton("🌟 Premium", callback_data=CALLBACK_MAIN_MENU_PREMIUM)],
            [InlineKeyboardButton("❓ Help", callback_data=CALLBACK_MAIN_MENU_HELP)],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            await update.callback_query.edit_message_text(text=message_text, reply_markup=reply_markup, parse_mode='MarkdownV2')
        elif update.message:
            await self.notifier.send_message(
                chat_id=user.id,
                text=message_text,
                reply_markup=reply_markup,
                parse_mode='MarkdownV2'
            )

    async def show_price_alerts_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Displays the price alert management sub-menu."""
        text = "Price Alert Management Menu:\n\n"
        text += "Manage your price alerts here. You can add, view, or delete alerts for specific tokens.\n\n"
        text += "Enter the token symbol (e.g., BTC, ETH) or the contract address. For small caps, you will need to specify the chain/network after entering the address.\n\n"
        keyboard = [
            [InlineKeyboardButton("➕ Add Price Alert", callback_data=CALLBACK_ALERTS_MENU_ADD)],
            [InlineKeyboardButton("🔔 View Price Alerts", callback_data=CALLBACK_ALERTS_MENU_VIEW)],
            [InlineKeyboardButton("🗑️ Delete Price Alert", callback_data=CALLBACK_ALERTS_MENU_DELETE)],
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data=CALLBACK_ALERTS_MENU_BACK_TO_MAIN)],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            query = update.callback_query
            await query.answer()
            await query.edit_message_text(text=text, reply_markup=reply_markup)
        elif update.message:
            await update.message.reply_text(text=text, reply_markup=reply_markup)
    
    async def show_wallet_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = "Wallet Management Menu:\n\n"
        text += "Manage your wallets here. You can add, remove, label, or list your wallets.\n\n"
        text += "Currently only compatible with EVM wallets (Base, BNB, Linea, etc.) with Solana support coming soon!.\n\n"
        keyboard = [
            [InlineKeyboardButton("➕ Add Wallet", callback_data=CALLBACK_WALLET_MENU_ADD)],
            [InlineKeyboardButton("➖ Remove Wallet", callback_data=CALLBACK_WALLET_MENU_REMOVE)],
            [InlineKeyboardButton("✏️ Label Wallet", callback_data=CALLBACK_WALLET_MENU_LABEL)],
            [InlineKeyboardButton("📋 List Wallets", callback_data=CALLBACK_WALLET_MENU_LIST)],
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data=CALLBACK_WALLET_MENU_BACK_TO_MAIN)],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            query = update.callback_query
            await query.answer()
            await query.edit_message_text(text=text, reply_markup=reply_markup)
        elif update.message:
            await update.message.reply_text(text=text, reply_markup=reply_markup)

    async def back_to_main_menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        await self.show_main_menu(update, context, message_text="Main Menu:")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        db_user, is_new_user = await self.db.create_user(user.id, user.username, user.first_name)

        if db_user:
            logger.info(f"User {user.id} started or interacted. New user: {is_new_user}")
            
            if is_new_user:
                # For new users, the specific welcome message is now handled in show_main_menu
                await self.show_main_menu(update, context, is_new_user=True)
            else:
                # For existing users, show the standard welcome back message
                initial_welcome_text = (
                    f"👋 Welcome back {escape_markdown(user.first_name or 'there', version=2)}\\!\n\n"
                    f"How can I assist you today?\n\n"
                    f"Current plan: {'Premium' if db_user.is_premium else 'Free'}\\."
                )
                await self.show_main_menu(update, context, message_text=initial_welcome_text)
        else:
            logger.error(f"Failed to create or retrieve user {user.id} in DB.")
            await update.message.reply_text("Sorry, there was an error setting up your profile. Please try again later.")
