import logging
from typing import Dict, Any, Optional
import math

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
from utils import get_token_info_from_contract_address, format_price_dynamically # Added format_price_dynamically
from wallet_manager import WalletManager # Added

logger = logging.getLogger(__name__)

# Conversation states
(
    ASK_TOKEN,
    ASK_CONDITION_PRICE,
    ASK_LABEL,
    CONFIRM_ALERT,
    TOKEN_CONFIRMATION_RECEIVED, 
    FINAL_CONFIRMATION_RECEIVED,
    CONFIRM_TOKEN_FROM_ADDRESS, # New state
) = range(7) # Adjusted range

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
    # CALLBACK_TOKEN_CANCEL can be reused
) = (
    "token_correct",
    "token_try_again",
    "token_cancel_creation",
    "create_alert_confirm",
    "create_alert_cancel",
    "skip_label",
    "addr_token_correct", # New
    "addr_token_retry_sym", # New
)

# This must match the one in core_handlers.py
BUTTON_CALLBACK_ADD_PRICE_ALERT = "main_menu_add_price_alert" 

class PriceAlertHandlers:
    def __init__(self, db: DatabaseManager, fetcher: PortfolioFetcher, notifier: Notifier, wallet_manager: WalletManager): # Added wallet_manager
        self.db = db
        self.fetcher = fetcher
        self.notifier = notifier
        self.wallet_manager = wallet_manager # Store wallet_manager instance

    async def alert_price_add_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data.clear()
        context.user_data['new_alert_info'] = {}
        message_text = (
            "Let's set up a new token price alert!\n\n"
            "First, please tell me the token you want to track. You can use its symbol (e.g., BTC), "
            "its name/slug (e.g., bitcoin), or its contract address (especially if symbol/name lookup isn't precise)."
        )
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            await query.message.reply_text(message_text) # Send as new message after button press
        elif update.message:
            await update.message.reply_text(message_text)
        else:
            logger.error("alert_price_add_start called without message or callback_query.")
            return ConversationHandler.END
        return ASK_TOKEN

    async def received_token_identifier(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user_input = update.message.text.strip()
        if not user_input:
            await update.message.reply_text("Please provide a token identifier (symbol, name, slug, or contract address).")
            return ASK_TOKEN

        # Check if input is a contract address
        is_address = await self.wallet_manager.validate_address(user_input)
        
        if is_address:
            logger.info(f"User provided potential contract address: {user_input}")
            token_info = await get_token_info_from_contract_address(self.fetcher, user_input) 
            
            if token_info and isinstance(token_info, dict):
                cmc_id = token_info.get("id")
                name = token_info.get("name")
                symbol = token_info.get("symbol")
                slug = token_info.get("slug")

                if cmc_id and name and symbol and slug:
                    context.user_data['new_alert_info']['cmc_id'] = cmc_id
                    context.user_data['new_alert_info']['token_display_name'] = f"{name} ({symbol})"
                    context.user_data['new_alert_info']['slug'] = slug
                    
                    quotes_data = await self.fetcher.fetch_cmc_token_quotes(ids=[cmc_id])
                    current_price = 0.0
                    if quotes_data and str(cmc_id) in quotes_data:
                        quote_usd = quotes_data[str(cmc_id)].get("quote", {}).get("USD", {})
                        current_price = quote_usd.get("price", 0.0)
                    context.user_data['new_alert_info']['token_current_price'] = current_price

                    confirmation_message = (
                        f"I found this token by address (via CoinMarketCap):\n"
                        f"Name: {name} ({symbol})\nSlug: {slug}\n"
                        f"Current Price: ${format_price_dynamically(current_price)}\n\nIs this correct?"
                    )
                    keyboard = [
                        [InlineKeyboardButton("✅ Yes, use this token", callback_data=CALLBACK_ADDRESS_TOKEN_CORRECT)],
                        [InlineKeyboardButton("🔄 No, let me use symbol/name", callback_data=CALLBACK_ADDRESS_TOKEN_RETRY_SYMBOL)],
                        [InlineKeyboardButton("❌ Cancel", callback_data=CALLBACK_TOKEN_CANCEL)],
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await update.message.reply_text(confirmation_message, reply_markup=reply_markup)
                    return CONFIRM_TOKEN_FROM_ADDRESS
                else:
                    logger.warning(f"Token info from address {user_input} missing essential fields: {token_info}")
            
            safe_user_input = escape_markdown(user_input, version=2)
            await update.message.reply_text(
                f"Sorry, I couldn't find any token information for the contract address `{safe_user_input}`\\. "
                f"Please double\\-check the address or try its symbol/name instead\\.",
                parse_mode='MarkdownV2'
            )
            return ASK_TOKEN

        # If not an address, proceed with symbol/name/slug lookup
        identifier_str = user_input
        logger.info(f"User provided identifier (symbol/name/slug): '{identifier_str}'")
        
        cmc_response_data = None
        query_key_for_response = None
        query_type = "" # For logging/messaging

        # Check if input is all uppercase and contains at least one letter (potential symbol)
        if identifier_str.isupper() and any(c.isalpha() for c in identifier_str):
            logger.info(f"Treating '{identifier_str}' as a SYMBOL for CMC query.")
            query_type = "symbol"
            cmc_response_data = await self.fetcher.fetch_cmc_token_quotes(symbols=[identifier_str])
            query_key_for_response = identifier_str # CMC keys response by the symbol provided
        else:
            # Treat as slug/name (slugs are typically lowercase)
            processed_identifier = identifier_str.lower()
            logger.info(f"Treating '{processed_identifier}' as a SLUG/NAME for CMC query.")
            query_type = "slug/name"
            cmc_response_data = await self.fetcher.fetch_cmc_token_quotes(slugs=[processed_identifier])
            # CMC keys response by the slug provided if found by slug.
            # If it was a name that resolved to a slug, the key might be the resolved slug.
            # This part can be tricky if the input name maps to a different slug.
            # For now, we'll try the processed_identifier as the key.
            query_key_for_response = processed_identifier


        selected_token_details = None
        if cmc_response_data:
            # Try direct key first (e.g. user input "BTC" -> key "BTC"; user input "bitcoin" -> key "bitcoin")
            if query_key_for_response in cmc_response_data:
                token_data_candidate = cmc_response_data[query_key_for_response]
                if isinstance(token_data_candidate, list) and token_data_candidate:
                    selected_token_details = token_data_candidate[0] 
                elif isinstance(token_data_candidate, dict):
                    selected_token_details = token_data_candidate
            # If not found by direct key, and it was a symbol query, CMC might return it under the ID if symbol was ambiguous
            # Or if it was a name that resolved to a slug, the key might be the actual slug.
            # This part is complex. For now, we rely on the direct key match.
            # A more robust solution might iterate data_map.values() if direct key fails.
            if not selected_token_details and len(cmc_response_data) == 1: # If only one result, assume it's the one
                 selected_token_details = next(iter(cmc_response_data.values()))
                 if isinstance(selected_token_details, list) and selected_token_details:
                     selected_token_details = selected_token_details[0]


        if selected_token_details and selected_token_details.get("id") and selected_token_details.get("name"):
            context.user_data['new_alert_info']['cmc_id'] = selected_token_details.get("id")
            name = selected_token_details.get("name", "N/A")
            symbol = selected_token_details.get("symbol", "N/A")
            context.user_data['new_alert_info']['token_display_name'] = f"{name} ({symbol})"
            context.user_data['new_alert_info']['slug'] = selected_token_details.get("slug")
            quote_usd = selected_token_details.get("quote", {}).get("USD", {})
            context.user_data['new_alert_info']['token_current_price'] = quote_usd.get("price", 0.0)
            cmc_rank = selected_token_details.get("cmc_rank", "N/A")
            platform_info = selected_token_details.get("platform")
            platform_name = platform_info.get("name", "N/A") if platform_info else "N/A"

            confirmation_message = (
                f"I found this token (via CoinMarketCap by {query_type}):\n"
                f"Name: {name} ({symbol})\nCMC Rank: {cmc_rank}\n"
                f"Price: ${format_price_dynamically(quote_usd.get('price', 0.0))}\n"
                f"Platform/Chain: {platform_name}\n\nIs this the correct token?"
            )
            keyboard = [
                [InlineKeyboardButton("✅ Yes, correct", callback_data=CALLBACK_TOKEN_CORRECT)],
                [InlineKeyboardButton("🔄 No, try again", callback_data=CALLBACK_TOKEN_TRY_AGAIN)],
                [InlineKeyboardButton("❌ Cancel", callback_data=CALLBACK_TOKEN_CANCEL)],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(confirmation_message, reply_markup=reply_markup)
            return TOKEN_CONFIRMATION_RECEIVED
        else:
            await update.message.reply_text(
                f"Sorry, I couldn't find a unique token for '{identifier_str}' using {query_type}. "
                f"Please try again with a more specific identifier or a contract address."
            )
            return ASK_TOKEN

    async def token_confirmation_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        await query.answer()
        if query.data == CALLBACK_TOKEN_CORRECT:
            await query.edit_message_text(text=f"Great! Token confirmed: {context.user_data['new_alert_info']['token_display_name']}")
            await query.message.reply_text("Now, tell me the condition and target price.\nExample: `above 150.50` or `below 0.75`")
            return ASK_CONDITION_PRICE
        elif query.data == CALLBACK_TOKEN_TRY_AGAIN:
            await query.edit_message_text(text="Okay, let's try identifying the token again.")
            await query.message.reply_text("Please tell me the token you want to track (symbol, name, slug, or contract address).")
            context.user_data['new_alert_info'] = {} # Clear for fresh input
            return ASK_TOKEN
        elif query.data == CALLBACK_TOKEN_CANCEL:
            await query.edit_message_text(text="Alert creation cancelled.")
            context.user_data.clear()
            return ConversationHandler.END
        return ConversationHandler.END # Should not be reached

    async def confirm_token_from_address_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles user confirmation after token is identified by contract address."""
        query = update.callback_query
        await query.answer()
        alert_info = context.user_data.get('new_alert_info', {})

        if query.data == CALLBACK_ADDRESS_TOKEN_CORRECT:
            # Token is confirmed, proceed directly to asking for condition and price
            confirmed_token_name = alert_info.get('token_display_name', 'the selected token')
            await query.edit_message_text(text=f"Great\! Token confirmed: {escape_markdown(confirmed_token_name, version=2)}\\.", parse_mode='MarkdownV2')
            await query.message.reply_text("Now, tell me the condition and target price.\nExample: `above 150.50` or `below 0.75`")
            return ASK_CONDITION_PRICE

        elif query.data == CALLBACK_ADDRESS_TOKEN_RETRY_SYMBOL:
            await query.edit_message_text(text="Okay, let's try identifying the token using its symbol or name.")
            await query.message.reply_text("Please tell me the token you want to track (symbol, name, or slug).")
            context.user_data['new_alert_info'] = {} # Clear info for fresh start with symbol/name
            return ASK_TOKEN
        elif query.data == CALLBACK_TOKEN_CANCEL: # Reusing cancel
            await query.edit_message_text(text="Alert creation cancelled.")
            context.user_data.clear()
            return ConversationHandler.END
        return ConversationHandler.END # Should not be reached

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
        context.user_data['new_alert_info']['target_price'] = target_price
        keyboard = [[InlineKeyboardButton("Skip Label (use default)", callback_data=CALLBACK_SKIP_LABEL)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
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
        return await self._confirm_alert_details(update, context)

    async def skip_label_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        await query.answer()
        alert_info = context.user_data['new_alert_info']
        default_label = f"{alert_info['token_display_name']} {alert_info['condition']} ${alert_info['target_price']:,.2f}"
        alert_info['label'] = default_label[:50]
        await query.edit_message_text(text=f"Label skipped. Using default: '{alert_info['label']}'")
        return await self._confirm_alert_details(query.message, context, is_callback=True)

    async def _confirm_alert_details(self, update_obj: Update | Any, context: ContextTypes.DEFAULT_TYPE, is_callback: bool = False) -> int:
        alert_info = context.user_data['new_alert_info']
        label = alert_info.get('label', 'N/A')
        token_display_name = alert_info.get('token_display_name', 'N/A')
        condition = alert_info.get('condition', 'N/A')
        target_price = alert_info.get('target_price', 0.0)
        current_price = alert_info.get('token_current_price', 0.0)

        message_text = (
            f"Please confirm your new alert:\n\n"
            f"🔔 Label: {label}\n🪙 Token: {token_display_name}\n"
            f"🎯 Condition: {condition.capitalize()} ${format_price_dynamically(target_price)}\n"
            f"   (Current Price: ${format_price_dynamically(current_price)})\n")
        keyboard = [
            [InlineKeyboardButton("✅ Create Alert", callback_data=CALLBACK_CREATE_ALERT_CONFIRM)],
            [InlineKeyboardButton("❌ Cancel", callback_data=CALLBACK_CREATE_ALERT_CANCEL)],]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        target_message_obj = update_obj.message if hasattr(update_obj, 'message') and update_obj.message else \
                             (update_obj.callback_query.message if hasattr(update_obj, 'callback_query') and update_obj.callback_query else update_obj)
        await target_message_obj.reply_text(message_text, reply_markup=reply_markup)
        return FINAL_CONFIRMATION_RECEIVED
        
    async def confirm_add_alert_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        await query.answer()
        alert_info = context.user_data['new_alert_info']
        if query.data == CALLBACK_CREATE_ALERT_CONFIRM:
            created_alert = await self.db.create_token_price_alert(
                user_id=query.from_user.id, cmc_id=alert_info['cmc_id'],
                token_display_name=alert_info['token_display_name'], target_price=alert_info['target_price'],
                condition=alert_info['condition'], label=alert_info['label'])
            if created_alert:
                await query.edit_message_text(text=f"✅ Alert '{alert_info['label']}' created successfully!")
            else:
                await query.edit_message_text(text="❌ Failed to create alert. Please try again or contact support.")
        elif query.data == CALLBACK_CREATE_ALERT_CANCEL:
            await query.edit_message_text(text="Alert creation cancelled.")
        context.user_data.clear()
        return ConversationHandler.END

    async def cancel_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        reply_text = "Alert creation process cancelled."
        if update.message: await update.message.reply_text(reply_text)
        elif update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(reply_text)
        context.user_data.clear()
        return ConversationHandler.END

    async def alert_price_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        alerts = await self.db.get_user_token_price_alerts(user_id=user_id, only_active=True)
        if not alerts:
            await update.message.reply_text("You have no active token price alerts.")
            return
        message_parts = ["Your active token price alerts:"]
        for alert in alerts:
            conditions = alert.conditions
            label_md = escape_markdown(conditions.get('label', 'N/A'), version=2)
            token_name_md = escape_markdown(alert.token_display_name or "Unknown Token", version=2)
            condition_type_md = escape_markdown(conditions.get('condition', 'N/A').capitalize(), version=2)
            target_price = conditions.get('target_price', 'N/A')
            target_price_str = f"${target_price:,.2f}" if isinstance(target_price, (int, float)) else "N/A"
            target_price_md = escape_markdown(target_price_str, version=2)
            message_parts.append(f"\n\n🔔 *Label*: _{label_md}_\n🪙 *Token*: {token_name_md}\n🎯 *Condition*: {condition_type_md} `{target_price_md}`")
        full_message = "\n".join(message_parts)
        if len(full_message) > 4096: full_message = full_message[:4090] + "\n\n\\.\\.\\."
        await update.message.reply_text(full_message, parse_mode="MarkdownV2")

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
        success = await self.db.deactivate_alert_and_log_trigger(alert_id=alert_to_delete.alert_id)
        if success:
            await update.message.reply_text(f"✅ Alert '{label_to_delete}' has been deactivated (deleted).")
        else:
            await update.message.reply_text(f"❌ Could not delete alert '{label_to_delete}'. Please try again.")

    @staticmethod
    def get_price_alert_conversation_handler(price_alert_handlers: "PriceAlertHandlers") -> ConversationHandler:
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("alert_price_create", price_alert_handlers.alert_price_add_start),
                CallbackQueryHandler(price_alert_handlers.alert_price_add_start, pattern=f"^{BUTTON_CALLBACK_ADD_PRICE_ALERT}$")
            ],
            states={
                ASK_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, price_alert_handlers.received_token_identifier)],
                CONFIRM_TOKEN_FROM_ADDRESS: [ 
                    CallbackQueryHandler(price_alert_handlers.confirm_token_from_address_callback, pattern=f"^({CALLBACK_ADDRESS_TOKEN_CORRECT}|{CALLBACK_ADDRESS_TOKEN_RETRY_SYMBOL}|{CALLBACK_TOKEN_CANCEL})$")
                ],
                TOKEN_CONFIRMATION_RECEIVED: [ 
                    CallbackQueryHandler(price_alert_handlers.token_confirmation_callback, pattern=f"^({CALLBACK_TOKEN_CORRECT}|{CALLBACK_TOKEN_TRY_AGAIN}|{CALLBACK_TOKEN_CANCEL})$")
                ],
                ASK_CONDITION_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, price_alert_handlers.received_condition_price)],
                ASK_LABEL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, price_alert_handlers.received_label),
                    CallbackQueryHandler(price_alert_handlers.skip_label_callback, pattern=f"^{CALLBACK_SKIP_LABEL}$")
                ],
                FINAL_CONFIRMATION_RECEIVED: [
                    CallbackQueryHandler(price_alert_handlers.confirm_add_alert_callback, pattern=f"^({CALLBACK_CREATE_ALERT_CONFIRM}|{CALLBACK_CREATE_ALERT_CANCEL})$")
                ],
            },
            fallbacks=[
                CommandHandler("cancel", price_alert_handlers.cancel_conversation),
                CallbackQueryHandler(price_alert_handlers.cancel_conversation, pattern=f"^({CALLBACK_TOKEN_CANCEL}|{CALLBACK_CREATE_ALERT_CANCEL})$") 
            ],
            per_message=False
        )
        return conv_handler
