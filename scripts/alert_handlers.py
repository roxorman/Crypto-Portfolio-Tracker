
import logging
from typing import Dict, Any, Optional
import math
import json
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)
from telegram.helpers import escape_markdown

# Assuming these modules and classes will exist or be adjusted
from db_manager import DatabaseManager
from api_fetcher import PortfolioFetcher
from notifier import Notifier
from config import Config
from utils import get_token_info_from_contract_address, format_price_dynamically # Added format_price_dynamically
from wallet_manager import WalletManager
from core_handlers import CALLBACK_ALERTS_MENU_ADD, CoreHandlers

logger = logging.getLogger(__name__)

# Conversation states
(
    ASK_TOKEN,
    ASK_CONDITION_PRICE,
    ASK_LABEL,
    CONFIRM_ALERT,
    TOKEN_CONFIRMATION_RECEIVED,
    FINAL_CONFIRMATION_RECEIVED,
    CONFIRM_TOKEN_FROM_ADDRESS,
    REACTIVATE_PRICE_RECEIVED,
    ASK_NETWORK,  # New state for CoinGecko fallback
) = range(9)

# Callback data constants
(
    CALLBACK_TOKEN_CORRECT,
    CALLBACK_TOKEN_TRY_AGAIN,
    CALLBACK_TOKEN_CANCEL,
    CALLBACK_CREATE_ALERT_CONFIRM,
    CALLBACK_CREATE_ALERT_CANCEL,
    CALLBACK_SKIP_LABEL,
    CALLBACK_ADDRESS_TOKEN_CORRECT, # New
    CALLBACK_ADDRESS_TOKEN_RETRY_SYMBOL, # New
    CALLBACK_REACTIVATE_ALERT,
    CALLBACK_CONFIRM_DEACTIVATE_ALERT,
) = (
    "token_correct",
    "token_try_again",
    "token_cancel_creation",
    "create_alert_confirm",
    "create_alert_cancel",
    "skip_label",
    "addr_token_correct", # New
    "addr_token_retry_sym", # New
    "reactivate_alert",
    "confirm_deactivate_alert",
)

# Callback data for the delete flow
CALLBACK_DELETE_ALERT_PREFIX = "delete_alert_id:"
CALLBACK_REACTIVATE_ALERT_PREFIX = "reactivate_alert_id:"
CALLBACK_DEACTIVATE_ALERT_PREFIX = "deactivate_alert_id:"
CALLBACK_BACK_TO_ALERTS_MENU = "back_to_alerts_menu"


class PriceAlertHandlers:
    def __init__(self, db: DatabaseManager, fetcher: PortfolioFetcher, notifier: Notifier, wallet_manager: WalletManager, config: Config, core_handlers: "CoreHandlers"):
        self.db = db
        self.fetcher = fetcher
        self.notifier = notifier
        self.wallet_manager = wallet_manager
        self.core_handlers = core_handlers
        self.config = config
        
    async def start_price_alert_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Entry point for the Add Price Alert button in the main menu."""
        return await self.alert_price_add_start(update, context)

    # --- Delete Alert Flow ---
    async def delete_alert_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Starts the interactive process to delete an alert."""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        alerts = await self.db.get_user_token_price_alerts(user_id=user_id, only_active=True)

        if not alerts:
            keyboard = [[InlineKeyboardButton("⬅️ Back to Alerts Menu", callback_data=CALLBACK_BACK_TO_ALERTS_MENU)]]
            await query.edit_message_text(
                text="You have no active alerts to delete.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        keyboard = []
        for alert in alerts:
            # Truncate label to fit on a button
            label = alert.conditions.get('label', f"Alert ID {alert.alert_id}")
            button_text = label[:60] # Limit button text length
            callback_data = f"{CALLBACK_DELETE_ALERT_PREFIX}{alert.alert_id}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
        keyboard.append([InlineKeyboardButton("⬅️ Back to Alerts Menu", callback_data=CALLBACK_BACK_TO_ALERTS_MENU)])
        
        await query.edit_message_text(
            text="Select an alert to delete:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def handle_delete_alert_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles the user's selection of an alert to delete."""
        query = update.callback_query
        user_id = query.from_user.id
        
        try:
            alert_id_to_delete = int(query.data.split(':')[1])
        except (IndexError, ValueError):
            await query.answer("Error: Invalid alert selection.", show_alert=True)
            return
        
        success = await self.db.delete_alert_by_id(alert_id_to_delete, user_id)
        
        if success:
            await query.answer("✅ Alert deleted successfully.", show_alert=True)
        else:
            await query.answer("❌ Error deleting alert. It may have already been removed.", show_alert=True)

        # Refresh the list of alerts
        await self.delete_alert_start(update, context)


    # --- Add Alert Conversation ---
    async def alert_price_add_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user_id = update.effective_user.id

        # --- NEW LIMIT CHECK ---
        user, _ = await self.db.create_user(user_id)
        tier_config = self.config.get_user_tier_config(user.is_premium)
        current_alerts = await self.db.get_user_token_price_alerts(user_id, only_active=True)

        if len(current_alerts) >= tier_config["MAX_ALERTS"]:
            query = update.callback_query
            await query.answer()
            await query.edit_message_text(
                f"You have reached your limit of {tier_config['MAX_ALERTS']} active price alerts. "
                "Please delete an alert or upgrade to Premium to add more."
            )
            return ConversationHandler.END
        # --- END LIMIT CHECK ---
        context.user_data.clear()
        context.user_data['new_alert_info'] = {} # Clear previous data
        message_text = (
            "Let's set up a new token price alert!\n\n"
            "First, please tell me the token you want to track. You can use its symbol (e.g., BTC) "
            "or its contract address."
        )
        # Add a cancel button to the initial prompt
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data=CALLBACK_TOKEN_CANCEL)]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            query = update.callback_query
            await query.answer()
            # Send a new message for the prompt, leaving the menu visible
            await context.bot.send_message(chat_id=query.message.chat_id, text=message_text, reply_markup=reply_markup)
        elif update.message:
            await update.message.reply_text(message_text, reply_markup=reply_markup)
        else:
            logger.error("alert_price_add_start called without message or callback_query.")
            return ConversationHandler.END
        return ASK_TOKEN

    async def received_token_identifier(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user_input = update.message.text.strip()
        if not user_input:
            await update.message.reply_text("Please provide a token identifier (symbol or contract address).")
            return ASK_TOKEN

        context.user_data['original_input'] = user_input
        cancel_keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data=CALLBACK_TOKEN_CANCEL)]]

        try:
            # --- Primary API (CMC) ---
            token_data = await self.fetcher.get_cmc_token_details(user_input)

            if token_data and isinstance(token_data, dict) and token_data.get("id"):
                # ... (existing CMC success logic) ...
                return await self._handle_cmc_success(update, context, token_data)
            
            # --- Fallback to CoinGecko ---
            else:
                # If the input looks like a contract address, initiate the fallback flow.
                # Expanded heuristic to include addresses with '::' like SUI.
                is_potential_address = (
                    (bool(re.match(r'^[a-zA-Z0-9]+$', user_input)) and len(user_input) > 10) or
                    ('::' in user_input and user_input.startswith('0x'))
                )

                if is_potential_address:
                    logger.info(f"CMC lookup failed for '{user_input}'. It appears to be a contract address. Initiating CoinGecko fallback.")
                    context.user_data['new_alert_info'] = {'token_address': user_input}
                    await update.message.reply_text(
                        "Token not found via primary source. It looks like a contract address. "
                        "To try the on-chain fallback, please specify the network (e.g., Ethereum, Solana, Polygon) this token is on.",
                        reply_markup=InlineKeyboardMarkup(cancel_keyboard)
                    )
                    return ASK_NETWORK
                else:
                    # If it's not an address, it's likely a symbol that wasn't found.
                    safe_user_input = escape_markdown(user_input, version=2)
                    await update.message.reply_text(
                        f"Sorry, I couldn't find any token information for `{safe_user_input}`\\. "
                        f"Please double\\-check the identifier or try another one\\.",
                        parse_mode='MarkdownV2',
                        reply_markup=InlineKeyboardMarkup(cancel_keyboard)
                    )
                    return ASK_TOKEN

        except Exception as e:
            logger.exception(f"Error processing token identifier '{user_input}': {e}")
            await update.message.reply_text("An unexpected error occurred. The process will be cancelled.")
            return ConversationHandler.END

    async def _handle_cmc_success(self, update: Update, context: ContextTypes.DEFAULT_TYPE, token_data: dict) -> int:
        """Handles the logic when a token is successfully found on CMC."""
        cmc_id = token_data.get("id")
        name = token_data.get("name")
        symbol = token_data.get("symbol")

        platform_name = "N/A"
        platform_info = token_data.get("platform")
        if isinstance(platform_info, dict):
            platform_name = platform_info.get("name") or "N/A"

        current_price = 0.0
        quote_data = token_data.get("quote", {}).get("USD", {})
        if isinstance(quote_data, dict):
            price = quote_data.get("price")
            if isinstance(price, (int, float)):
                current_price = price

        context.user_data['new_alert_info'] = {
            'source': 'cmc',
            'cmc_id': cmc_id,
            'token_display_name': f"{name} ({symbol})",
            'token_current_price': current_price,
        }

        confirmation_message = (
            f"I found: {name} ({symbol}) on {platform_name}\n"
            f"Price: ${format_price_dynamically(current_price)}\n\nIs this correct?"
        )
        keyboard = [
            [InlineKeyboardButton("✅ Yes, use this token", callback_data=CALLBACK_TOKEN_CORRECT)],
            [InlineKeyboardButton("🔄 No, try again", callback_data=CALLBACK_TOKEN_TRY_AGAIN)],
            [InlineKeyboardButton("❌ Cancel", callback_data=CALLBACK_TOKEN_CANCEL)],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(confirmation_message, reply_markup=reply_markup)
        return TOKEN_CONFIRMATION_RECEIVED

    async def received_network(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles the network name input for the CoinGecko fallback."""
        network_input = update.message.text.strip().lower()
        alert_info = context.user_data.get('new_alert_info', {})
        token_address = alert_info.get('token_address')

        if not token_address:
            await update.message.reply_text("An error occurred. Could not find the token address. Please start over.")
            return ConversationHandler.END

        # Load networks.json
        try:
            with open('networks.json', 'r') as f:
                networks_data = json.load(f).get('data', [])
        except (FileNotFoundError, json.JSONDecodeError):
            logger.error("Could not load or parse networks.json.")
            await update.message.reply_text("Internal error: Could not access network data. Please try again later.")
            return ConversationHandler.END

        # Find matching network with improved logic
        matched_network = None
        
        # 1. First pass: exact matches (ID or full name)
        for network in networks_data:
            attrs = network.get('attributes', {})
            if network.get('id') == network_input or (attrs.get('name') and attrs.get('name').lower() == network_input):
                matched_network = network
                break
        
        # 2. Second pass: partial word match if no exact match was found
        if not matched_network:
            for network in networks_data:
                attrs = network.get('attributes', {})
                network_name_words = (attrs.get('name') or "").lower().split()
                if network_input in network_name_words:
                    matched_network = network
                    break
        
        if not matched_network:
            await update.message.reply_text(f"Network '{network_input}' not found. Please provide a valid network name or cancel.")
            return ASK_NETWORK

        network_id = matched_network['id']
        network_name = matched_network.get('attributes', {}).get('name', network_id)
        
        # Fetch detailed token info from CoinGecko
        token_details = await self.fetcher.fetch_coingecko_token_details(network_id, token_address)

        if not token_details:
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Try Again", callback_data="coingecko_retry_network"),
                    InlineKeyboardButton("⬅️ Go Back", callback_data=CALLBACK_TOKEN_TRY_AGAIN)
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"Could not find the token on the {network_name} network using the fallback. "
                "Please check the address and network, or try another token.",
                reply_markup=reply_markup
            )
            return ASK_NETWORK

        name = token_details.get('name')
        symbol = token_details.get('symbol')
        current_price = token_details.get('price_usd')

        token_display_name = f"{name} ({symbol})" if name and symbol else f"Token on {network_name}"
        
        context.user_data['new_alert_info'].update({
            'source': 'coingecko',
            'network_id': network_id,
            'token_display_name': token_display_name,
            'token_current_price': current_price,
        })

        await update.message.reply_text(f"Found: {token_display_name} on {network_name}\nPrice: ${format_price_dynamically(current_price)}")
        
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data=CALLBACK_TOKEN_CANCEL)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(chat_id=update.message.chat_id, text="Now, tell me the condition and target price.\nExample: `above 150.50` or `below 0.75`", reply_markup=reply_markup)
        return ASK_CONDITION_PRICE

    async def token_confirmation_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        await query.answer()
        if query.data == CALLBACK_TOKEN_CORRECT:
            # Send a new message for the next step, leaving the previous confirmation visible
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"Great! Token confirmed: {context.user_data['new_alert_info']['token_display_name']}")
            keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data=CALLBACK_TOKEN_CANCEL)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(chat_id=query.message.chat_id, text="Now, tell me the condition and target price.\nExample: `above 150.50` or `below 0.75`", reply_markup=reply_markup)
            return ASK_CONDITION_PRICE
        elif query.data == CALLBACK_TOKEN_TRY_AGAIN:
            # This is effectively a "back" button, so we edit the message to avoid clutter
            await query.edit_message_text(text="Okay, let's try identifying the token again.")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Please tell me the token you want to track (symbol or contract address)."
            )
            context.user_data['new_alert_info'] = {} # Clear for fresh input
            return ASK_TOKEN
        return ConversationHandler.END

    async def coingecko_retry_network_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles the 'Try Again' button press after a failed CoinGecko lookup."""
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Okay, please specify the network again (e.g., Ethereum, Base, Polygon).")
        return ASK_NETWORK

    async def confirm_token_from_address_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        await query.answer()
        alert_info = context.user_data.get('new_alert_info', {})
        if query.data == CALLBACK_ADDRESS_TOKEN_CORRECT:
            confirmed_token_name = alert_info.get('token_display_name', 'the selected token')
            # Send a new message for the next step, leaving the previous confirmation visible
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"Great! Token confirmed: {escape_markdown(confirmed_token_name, version=2)}.", parse_mode='MarkdownV2')
            keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data=CALLBACK_TOKEN_CANCEL)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(chat_id=query.message.chat_id, text="Now, tell me the condition and target price.\nExample: `above 150.50` or `below 0.75`", reply_markup=reply_markup)
            return ASK_CONDITION_PRICE
        elif query.data == CALLBACK_ADDRESS_TOKEN_RETRY_SYMBOL:
            await query.edit_message_text(text="Okay, let's try identifying the token using its symbol or name.")
            await query.message.reply_text("Please tell me the token you want to track (symbol, name, or slug).")
            context.user_data['new_alert_info'] = {}
            return ASK_TOKEN
        elif query.data == CALLBACK_TOKEN_CANCEL:
            # This is effectively a "back" button, so we edit the message to avoid clutter
            await query.edit_message_text(text="Alert creation cancelled.")
            context.user_data.clear()
            return ConversationHandler.END
        return ConversationHandler.END

    async def received_condition_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user_input = update.message.text.strip().lower()
        parts = user_input.split()
        if len(parts) != 2 or parts[0] not in ["above", "below"]:
            await update.message.reply_text("Invalid format. Please use 'above PRICE' or 'below PRICE'.\nExample: `above 150.50`")
            return ASK_CONDITION_PRICE
        condition = parts[0]
        try:
            target_price = float(parts[1])
            if target_price <= 0: raise ValueError("Price must be positive.")
        except ValueError:
            await update.message.reply_text("Invalid price. Please enter a positive number.\nExample: `above 150.50`")
            return ASK_CONDITION_PRICE
        context.user_data['new_alert_info']['condition'] = condition
        context.user_data['new_alert_info']['target_price'] = target_price # Already has Cancel
        keyboard = [[InlineKeyboardButton("Skip Label (use default)", callback_data=CALLBACK_SKIP_LABEL)]]
        reply_markup = InlineKeyboardMarkup(keyboard + [[InlineKeyboardButton("❌ Cancel", callback_data=CALLBACK_TOKEN_CANCEL)]])
        await update.message.reply_text(
            f"Condition set: {condition} ${format_price_dynamically(target_price)}.\n\nOptionally, give this alert a short label (e.g., 'SOL ATH watch'), or skip this.",
            reply_markup=reply_markup)
        return ASK_LABEL

    async def received_label(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        label = update.message.text.strip()
        if len(label) > 50:
            await update.message.reply_text("Label is too long (max 50 characters). Please try a shorter one.")
            return ASK_LABEL
        context.user_data['new_alert_info']['label'] = label
        return await self._confirm_alert_details(update.message, context)

    async def skip_label_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        await query.answer()
        alert_info = context.user_data['new_alert_info']
        default_label = f"{alert_info['token_display_name']} {alert_info['condition']} ${alert_info['target_price']:g}"
        alert_info['label'] = default_label[:60]
        await query.edit_message_text(text=f"Label skipped. Using default: '{alert_info['label']}'")
        return await self._confirm_alert_details(query.message, context)

    async def _confirm_alert_details(self, message, context: ContextTypes.DEFAULT_TYPE) -> int:
        alert_info = context.user_data['new_alert_info']
        label, token_display_name, condition = alert_info.get('label', 'N/A'), alert_info.get('token_display_name', 'N/A'), alert_info.get('condition', 'N/A')
        target_price, current_price = alert_info.get('target_price', 0.0), alert_info.get('token_current_price', 0.0)

        message_text = (f"Please confirm your new alert:\n\n"
                        f"🔔 Label: {label}\n🪙 Token: {token_display_name}\n"
                        f"🎯 Condition: {condition.capitalize()} ${format_price_dynamically(target_price)}\n"
                        f"   (Current Price: ${format_price_dynamically(current_price)})")
        keyboard = [[InlineKeyboardButton("✅ Create Alert", callback_data=CALLBACK_CREATE_ALERT_CONFIRM)],
                    [InlineKeyboardButton("❌ Cancel", callback_data=CALLBACK_CREATE_ALERT_CANCEL)],]
        await message.reply_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard))
        return FINAL_CONFIRMATION_RECEIVED
        
    async def confirm_add_alert_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        await query.answer()
        alert_info = context.user_data['new_alert_info']
        
        if query.data == CALLBACK_CREATE_ALERT_CANCEL:
            await query.edit_message_text(text="Alert creation cancelled.")
            context.user_data.clear()
            await self.core_handlers.show_price_alerts_menu(update, context)
            return ConversationHandler.END

        if query.data == CALLBACK_CREATE_ALERT_CONFIRM:
            created_alert = None
            if alert_info.get('source') == 'cmc':
                created_alert = await self.db.create_token_price_alert(
                    user_id=query.from_user.id, cmc_id=alert_info['cmc_id'],
                    token_display_name=alert_info['token_display_name'], target_price=alert_info['target_price'],
                    condition=alert_info['condition'], label=alert_info['label'])
            elif alert_info.get('source') == 'coingecko':
                created_alert = await self.db.create_coingecko_token_price_alert(
                    user_id=query.from_user.id,
                    token_address=alert_info['token_address'],
                    network_id=alert_info['network_id'],
                    token_display_name=alert_info['token_display_name'],
                    target_price=alert_info['target_price'],
                    condition=alert_info['condition'],
                    label=alert_info['label'],
                    polling_interval=210  # 3.5 minutes
                )

            if created_alert:
                await query.edit_message_text(text=f"✅ Alert '{alert_info['label']}' created successfully!")
            else:
                await query.edit_message_text(text="❌ Failed to create alert. An alert with this label may already exist, or an error occurred.")
        
        context.user_data.clear()
        await self.core_handlers.show_price_alerts_menu(update, context)
        return ConversationHandler.END

    async def handle_reactivate_alert(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles the 'Reactivate Alert' button press and asks for a new price."""
        query = update.callback_query
        await query.answer()
        
        try:
            alert_id = int(query.data.split(':')[1])
        except (IndexError, ValueError):
            await query.edit_message_text("Error: Invalid alert ID for reactivation.")
            return ConversationHandler.END

        context.user_data['reactivate_alert_id'] = alert_id

        await query.edit_message_text(
            "Now, tell me the new condition and target price.\n"
            "Example: `above 150.50` or `below 0.75`"
        )
        
        return REACTIVATE_PRICE_RECEIVED

    async def received_reactivate_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles the new price input for reactivating an alert."""
        user_input = update.message.text.strip().lower()
        alert_id = context.user_data.get('reactivate_alert_id')

        if not alert_id:
            await update.message.reply_text("An error occurred. Could not find the alert to reactivate. Please try again.")
            context.user_data.clear()
            return ConversationHandler.END

        parts = user_input.split()
        if len(parts) != 2 or parts[0] not in ["above", "below"]:
            await update.message.reply_text("Invalid format. Please use 'above PRICE' or 'below PRICE'.\nExample: `above 150.50`")
            return REACTIVATE_PRICE_RECEIVED

        condition = parts[0]
        try:
            target_price = float(parts[1])
            if target_price <= 0: raise ValueError("Price must be positive.")
        except ValueError:
            await update.message.reply_text("Invalid price. Please enter a positive number.\nExample: `above 150.50`")
            return REACTIVATE_PRICE_RECEIVED

        success = await self.db.reactivate_alert(alert_id, condition, target_price)

        if success:
            await update.message.reply_text("✅ Alert has been reactivated with the new price condition.")
        else:
            await update.message.reply_text("❌ Failed to reactivate the alert. It may have been deleted or an error occurred.")

        context.user_data.clear()
        return ConversationHandler.END

    async def handle_confirm_deactivate_alert(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles the 'Confirm & Deactivate' button press."""
        query = update.callback_query
        await query.answer()
        
        try:
            alert_id = int(query.data.split(':')[1])
        except (IndexError, ValueError):
            await query.edit_message_text("Error: Invalid alert ID for deactivation.")
            return

        # The alert is already inactive, so we just confirm to the user
        await query.edit_message_text("✅ Alert has been deactivated. You can reactivate it later from the alerts menu.")
    async def cancel_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        reply_text = "Alert creation process cancelled."
        if update.message: await update.message.reply_text(reply_text)
        elif update.callback_query:
            await update.callback_query.answer() # Acknowledge the button press
            # If it's a callback query, we should edit the message that contained the button
            # to indicate cancellation, then send the menu.
            await update.callback_query.edit_message_text(reply_text)
        context.user_data.clear()
        await self.core_handlers.show_price_alerts_menu(update, context)
        return ConversationHandler.END

    async def alert_price_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        alerts = await self.db.get_user_token_price_alerts(user_id=user_id, only_active=True)
        
        message_text = ""
        if not alerts:
            message_text = "You have no active token price alerts\\."
        else:
            message_parts = ["*Your active token price alerts:*"]
            for alert in alerts:
                conditions = alert.conditions
                label_md = escape_markdown(conditions.get('label', 'N/A'), version=2)
                token_name_md = escape_markdown(alert.token_display_name or "Unknown Token", version=2)
                condition_type_md = escape_markdown(conditions.get('condition', 'N/A').capitalize(), version=2)
                target_price = conditions.get('target_price', 'N/A')
                target_price_str = f"${format_price_dynamically(target_price)}" if isinstance(target_price, (int, float)) else "N/A"
                target_price_md = escape_markdown(target_price_str, version=2)
                message_parts.append(f"\n\n🔔 *Label*: _{label_md}_\n🪙 *Token*: {token_name_md}\n🎯 *Condition*: {condition_type_md} `{target_price_md}`")
            
            message_text = "\n".join(message_parts)

        if update.callback_query:
            await update.callback_query.edit_message_text(text=message_text, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Alerts Menu", callback_data=CALLBACK_BACK_TO_ALERTS_MENU)]]))
        elif update.message:
            await update.message.reply_text(text=message_text, parse_mode="MarkdownV2")

    async def alert_price_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not context.args:
            await update.message.reply_text("Please provide the label of the alert to delete.\nUsage: `/alert_price_delete Your Alert Label`")
            return
        label_to_delete = " ".join(context.args)
        alert_to_delete = await self.db.find_user_token_price_alert_by_label(user_id=user_id, label=label_to_delete)
        if not alert_to_delete:
            await update.message.reply_text(f"No active alert found with the label: '{label_to_delete}'. Labels are case-sensitive.")
            return
        # Use delete_alert_by_id for direct permanent deletion
        success = await self.db.delete_alert_by_id(alert_id=alert_to_delete.alert_id, user_id=user_id)
        if success:
            await update.message.reply_text(f"✅ Alert '{label_to_delete}' has been deleted.")
        else:
            await update.message.reply_text(f"❌ Could not delete alert '{label_to_delete}'. Please try again.")

    @staticmethod
    def get_price_alert_conversation_handler(price_alert_handlers: "PriceAlertHandlers") -> ConversationHandler:
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("alert_price_create", price_alert_handlers.alert_price_add_start),
                CallbackQueryHandler(price_alert_handlers.alert_price_add_start, pattern=f"^{CALLBACK_ALERTS_MENU_ADD}$"),
                CallbackQueryHandler(price_alert_handlers.handle_reactivate_alert, pattern=f"^{CALLBACK_REACTIVATE_ALERT_PREFIX}")
            ],
            states={
                ASK_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, price_alert_handlers.received_token_identifier)],
                ASK_NETWORK: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, price_alert_handlers.received_network),
                    CallbackQueryHandler(price_alert_handlers.coingecko_retry_network_callback, pattern="^coingecko_retry_network$"),
                    CallbackQueryHandler(price_alert_handlers.token_confirmation_callback, pattern=f"^{CALLBACK_TOKEN_TRY_AGAIN}$") # Re-use for "Go Back"
                ],
                CONFIRM_TOKEN_FROM_ADDRESS: [
                    CallbackQueryHandler(price_alert_handlers.confirm_token_from_address_callback, pattern=f"^({CALLBACK_ADDRESS_TOKEN_CORRECT}|{CALLBACK_ADDRESS_TOKEN_RETRY_SYMBOL})$")
                ],
                TOKEN_CONFIRMATION_RECEIVED: [
                    CallbackQueryHandler(price_alert_handlers.token_confirmation_callback, pattern=f"^({CALLBACK_TOKEN_CORRECT}|{CALLBACK_TOKEN_TRY_AGAIN})$")
                ],
                ASK_CONDITION_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, price_alert_handlers.received_condition_price)],
                ASK_LABEL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, price_alert_handlers.received_label),
                    CallbackQueryHandler(price_alert_handlers.skip_label_callback, pattern=f"^{CALLBACK_SKIP_LABEL}$")
                ],
                FINAL_CONFIRMATION_RECEIVED: [
                    CallbackQueryHandler(price_alert_handlers.confirm_add_alert_callback, pattern=f"^({CALLBACK_CREATE_ALERT_CONFIRM}|{CALLBACK_CREATE_ALERT_CANCEL})$")
                ],
                REACTIVATE_PRICE_RECEIVED: [MessageHandler(filters.TEXT & ~filters.COMMAND, price_alert_handlers.received_reactivate_price)],
            },
            fallbacks=[
                CommandHandler("cancel", price_alert_handlers.cancel_conversation),
                CallbackQueryHandler(price_alert_handlers.cancel_conversation, pattern=f"^{CALLBACK_TOKEN_CANCEL}$"),
                CallbackQueryHandler(price_alert_handlers.handle_confirm_deactivate_alert, pattern=f"^{CALLBACK_DEACTIVATE_ALERT_PREFIX}"),
            ],
            per_message=False
        )
        return conv_handler
