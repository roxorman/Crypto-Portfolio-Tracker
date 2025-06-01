# wallet_management_handlers.py
from telegram import Update
from telegram.ext import ContextTypes
from db_manager import DatabaseManager
from notifier import Notifier
from utils import format_address
from telegram.helpers import escape_markdown
from web3 import Web3 # Still needed for norm_address, or pass type from WalletManager
import logging
import re
from typing import Optional

from telegram.ext import ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from wallet_manager import WalletManager # Import WalletManager

logger = logging.getLogger(__name__)

# Conversation states for adding a wallet
ASK_WALLET_ADDRESS, ASK_WALLET_LABEL = range(2)
# Conversation states for removing a wallet (ensure unique range)
ASK_WALLET_TO_REMOVE_IDENTIFIER, CONFIRM_WALLET_REMOVAL = range(ASK_WALLET_LABEL + 1, ASK_WALLET_LABEL + 3)
# Conversation states for labeling a wallet (ensure unique range)
ASK_WALLET_TO_LABEL_IDENTIFIER, ASK_NEW_WALLET_LABEL = range(CONFIRM_WALLET_REMOVAL + 1, CONFIRM_WALLET_REMOVAL + 3)


# Callback data
CALLBACK_SKIP_WALLET_LABEL = "skip_wallet_label"
CALLBACK_CANCEL_WALLET_ADD = "cancel_wallet_add" # Used in fallbacks
CALLBACK_WALLET_REMOVE_CONFIRM_YES = "wallet_remove_yes"
CALLBACK_WALLET_REMOVE_CONFIRM_NO = "wallet_remove_no"
CALLBACK_CANCEL_WALLET_REMOVE = "cancel_wallet_remove" # Used in fallbacks
CALLBACK_CANCEL_WALLET_LABEL = "cancel_wallet_label" # Used in fallbacks


# Button patterns (must match core_handlers.py)
BUTTON_CALLBACK_WALLET_MENU_ADD = "wallet_menu_add"
BUTTON_CALLBACK_WALLET_MENU_REMOVE = "wallet_menu_remove"
BUTTON_CALLBACK_WALLET_MENU_LABEL = "wallet_menu_label"
# BUTTON_CALLBACK_WALLET_MENU_LIST is handled directly by list_wallets method

class WalletManagementHandlers:
    def __init__(self, db_manager: DatabaseManager, notifier: Notifier, wallet_manager: WalletManager): # Add wallet_manager
        self.db = db_manager
        self.notifier = notifier
        self.wallet_manager = wallet_manager # Store wallet_manager instance
        logger.info("WalletManagementHandlers initialized.")

    # --- Add Wallet Conversation ---
    async def add_wallet_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data.clear() # Clear previous conversation data
        context.user_data['new_wallet_info'] = {}
        text = "Please send me the wallet address you'd like to add."
        query = update.callback_query
        await query.answer()
        # DON'T edit the sub-menu message, send a new one instead.
        # await query.edit_message_reply_markup(reply_markup=None) # Removed
        await context.bot.send_message(chat_id=query.message.chat_id, text=text)
        return ASK_WALLET_ADDRESS

    async def received_wallet_address(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        address = update.message.text.strip()
        user_id = update.effective_user.id
        
        # Use WalletManager for validation
        if not await self.wallet_manager.validate_address(address):
            await update.message.reply_text("That doesn't look like a valid wallet address. Please try again, or type /cancel_wallet_add to stop.")
            return ASK_WALLET_ADDRESS
        
        # Normalize address - WalletManager doesn't normalize, so we do it here or get type
        # For now, simple EVM-like normalization for DB storage if it's an EVM address.
        # A more robust way would be to get type from wallet_manager and normalize accordingly.
        # Or store as is if validation passes. Let's assume validation implies it's in a good format for now.
        # For DB consistency, if it's EVM, lowercase it.
        # This part might need refinement based on how `get_address_type` is used or if `validate_address` also returns type.
        norm_address = address
        # Attempt to get type to decide on normalization for DB.
        # This is a bit redundant if validate_address already did similar checks.
        # Consider if WalletManager should also provide a canonical/normalized form.
        addr_type = await self.wallet_manager.get_address_type(address)
        if addr_type == "evm":
            norm_address = address.lower()
        # For Solana, addresses are case-sensitive in some contexts but often used case-insensitively.
        # The regex in WalletManager allows mixed case. Storing as received after validation is one approach.

        existing_wallet = await self.db.get_wallet_by_address(user_id, norm_address)
        if existing_wallet:
            safe_addr_fmt = escape_markdown(format_address(norm_address), version=2)
            await update.message.reply_text(
                rf"ℹ️ Wallet `{safe_addr_fmt}` is already being tracked\. You can label it using the main menu if you wish\.",
                parse_mode='MarkdownV2')
            context.user_data.clear()
            return ConversationHandler.END

        context.user_data['new_wallet_info']['address'] = norm_address # Store the potentially normalized address
        
        keyboard = [[InlineKeyboardButton("Skip Label", callback_data=CALLBACK_SKIP_WALLET_LABEL)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            rf"Got it\. Now, optionally send me a label for this wallet \(e\.g\., 'My Main ETH Wallet'\)\.\nOr, you can skip adding a label\.",
            reply_markup=reply_markup, parse_mode='MarkdownV2')
        return ASK_WALLET_LABEL

    async def _finalize_add_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE, label: Optional[str]) -> int:
        user_id = update.effective_user.id
        address = context.user_data['new_wallet_info']['address'] # This is already normalized
        safe_addr_fmt = escape_markdown(format_address(address), version=2)
        if label:
            if await self.db.check_label_exists(user_id, label):
                safe_label = escape_markdown(label, version=2)
                reply_method = update.message.reply_text if update.message else context.bot.send_message
                chat_id_to_reply = update.message.chat_id if update.message else update.callback_query.message.chat_id
                await reply_method(
                    chat_id=chat_id_to_reply,
                    text=rf"❌ Failed: Another wallet already has the label '{safe_label}'\\. Labels must be unique\\. Please try a different label, or type /cancel_wallet_add to stop\.",
                    parse_mode='MarkdownV2')
                return ASK_WALLET_LABEL
        new_wallet = await self.db.add_wallet_identity(user_id, address, label) # Pass normalized address
        reply_text_final = f"✅ Wallet `{safe_addr_fmt}` added" + (f" with label '{escape_markdown(label, version=2)}'" if label else "") + r"\." if new_wallet else f"❌ Failed to add wallet `{safe_addr_fmt}`\\. An internal error occurred\\."
        
        if update.callback_query and update.callback_query.data == CALLBACK_SKIP_WALLET_LABEL: 
            await update.callback_query.edit_message_text(text=reply_text_final, parse_mode='MarkdownV2')
        elif update.message: 
            await update.message.reply_text(text=reply_text_final, parse_mode='MarkdownV2')
        
        context.user_data.clear()
        return ConversationHandler.END

    async def received_wallet_label(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        label = update.message.text.strip()
        if len(label) > 50:
            await update.message.reply_text("Label is too long (max 50 characters). Please try a shorter one, or type /cancel_wallet_add to stop.")
            return ASK_WALLET_LABEL
        return await self._finalize_add_wallet(update, context, label)

    async def skip_wallet_label_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text="Okay, skipping label for this wallet...") 
        return await self._finalize_add_wallet(update, context, None)

    async def cancel_add_wallet_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        reply_text = "Adding wallet process cancelled."
        if update.message: await update.message.reply_text(reply_text)
        elif update.callback_query:
            await update.callback_query.answer()
            try:
                await update.callback_query.edit_message_text(text=reply_text)
            except Exception:
                await context.bot.send_message(chat_id=update.callback_query.message.chat_id, text=reply_text)
        context.user_data.clear()
        return ConversationHandler.END
    # --- End Add Wallet Conversation ---

    # --- Remove Wallet Conversation ---
    async def remove_wallet_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data.clear() 
        context.user_data['remove_wallet_info'] = {}
        query = update.callback_query
        await query.answer()
        await context.bot.send_message(chat_id=query.message.chat_id, text="Please send the address or label of the wallet you want to remove.")
        return ASK_WALLET_TO_REMOVE_IDENTIFIER

    async def received_wallet_to_remove_identifier(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        identifier = update.message.text.strip()
        user_id = update.effective_user.id
        wallet_to_delete = await self.db.find_user_wallet(user_id, identifier)

        if not wallet_to_delete:
            safe_id = escape_markdown(identifier, version=2)
            await update.message.reply_text(f"❌ Wallet '{safe_id}' not found\\. Please try again, or type /cancel_wallet_remove to stop\\.", parse_mode='MarkdownV2')
            return ASK_WALLET_TO_REMOVE_IDENTIFIER

        context.user_data['remove_wallet_info']['wallet_id'] = wallet_to_delete.wallet_id
        context.user_data['remove_wallet_info']['address_fmt'] = escape_markdown(format_address(wallet_to_delete.address), version=2)
        context.user_data['remove_wallet_info']['label_part'] = f" \\(Label: '{escape_markdown(wallet_to_delete.label, version=2)}'\\)" if wallet_to_delete.label else ""
        
        text = f"Found wallet: `{context.user_data['remove_wallet_info']['address_fmt']}`{context.user_data['remove_wallet_info']['label_part']}\\.\nAre you sure you want to remove it?"
        keyboard = [
            [InlineKeyboardButton("✅ Yes, Remove", callback_data=CALLBACK_WALLET_REMOVE_CONFIRM_YES)],
            [InlineKeyboardButton("❌ No, Cancel", callback_data=CALLBACK_WALLET_REMOVE_CONFIRM_NO)],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')
        return CONFIRM_WALLET_REMOVAL

    async def confirm_remove_wallet_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        if query.data == CALLBACK_WALLET_REMOVE_CONFIRM_YES:
            wallet_id = context.user_data['remove_wallet_info']['wallet_id']
            address_fmt = context.user_data['remove_wallet_info']['address_fmt']
            label_part = context.user_data['remove_wallet_info']['label_part'] 
            success = await self.db.delete_wallet_identity(user_id, wallet_id)
            if success:
                await query.edit_message_text(text=f"🗑️ Wallet `{address_fmt}`{label_part} removed successfully\\.", parse_mode='MarkdownV2')
            else:
                await query.edit_message_text(text=f"❌ Failed to remove wallet `{address_fmt}`{label_part}\\. An internal error occurred\\.", parse_mode='MarkdownV2')
        elif query.data == CALLBACK_WALLET_REMOVE_CONFIRM_NO:
            await query.edit_message_text(text="Wallet removal cancelled.")
        
        context.user_data.clear()
        return ConversationHandler.END

    async def cancel_remove_wallet_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        reply_text = "Removing wallet process cancelled."
        if update.message: await update.message.reply_text(reply_text)
        elif update.callback_query:
            await update.callback_query.answer()
            try: await update.callback_query.edit_message_text(text=reply_text)
            except Exception: await context.bot.send_message(chat_id=update.callback_query.message.chat_id, text=reply_text)
        context.user_data.clear()
        return ConversationHandler.END
    # --- End Remove Wallet Conversation ---

    # --- Label Wallet Conversation ---
    async def label_wallet_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data.clear() 
        context.user_data['label_wallet_info'] = {}
        query = update.callback_query
        await query.answer()
        await context.bot.send_message(chat_id=query.message.chat_id, text="Please send the address or current label of the wallet you want to (re)label.")
        return ASK_WALLET_TO_LABEL_IDENTIFIER

    async def received_wallet_to_label_identifier(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        identifier = update.message.text.strip()
        user_id = update.effective_user.id
        wallet = await self.db.find_user_wallet(user_id, identifier)

        if not wallet:
            safe_id = escape_markdown(identifier, version=2)
            await update.message.reply_text(f"❌ Wallet '{safe_id}' not found\\. Please try again, or type /cancel_wallet_label to stop\\.", parse_mode='MarkdownV2')
            return ASK_WALLET_TO_LABEL_IDENTIFIER
        
        context.user_data['label_wallet_info']['wallet_id'] = wallet.wallet_id
        context.user_data['label_wallet_info']['address'] = wallet.address
        context.user_data['label_wallet_info']['current_label'] = wallet.label
        safe_addr_fmt = escape_markdown(format_address(wallet.address), version=2)
        current_label_text = f" \\(Current label: '{escape_markdown(wallet.label, version=2)}'\\)" if wallet.label else " \\(Currently unlabelled\\)"
        
        await update.message.reply_text(f"Found wallet: `{safe_addr_fmt}`{current_label_text}\\. What would you like as the new label?", parse_mode='MarkdownV2')
        return ASK_NEW_WALLET_LABEL

    async def received_new_wallet_label(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        new_label = update.message.text.strip()
        user_id = update.effective_user.id
        wallet_id = context.user_data['label_wallet_info']['wallet_id']
        address = context.user_data['label_wallet_info']['address']
        safe_addr_fmt = escape_markdown(format_address(address), version=2)

        if len(new_label) > 50:
            await update.message.reply_text("Label is too long (max 50 characters). Please try a shorter one, or type /cancel_wallet_label to stop.")
            return ASK_NEW_WALLET_LABEL
        
        if await self.db.check_label_exists(user_id, new_label, exclude_wallet_id=wallet_id):
            safe_new_label = escape_markdown(new_label, version=2)
            await update.message.reply_text(f"❌ Failed: Another wallet already has the label '{safe_new_label}'\\. Labels must be unique\\. Please try again, or type /cancel_wallet_label to stop\\.", parse_mode='MarkdownV2')
            return ASK_NEW_WALLET_LABEL

        success = await self.db.update_wallet_label(user_id, address, new_label)
        safe_new_label_fmt = escape_markdown(new_label, version=2)
        if success:
            await update.message.reply_text(f"✏️ Label for `{safe_addr_fmt}` set to '{safe_new_label_fmt}'\\.", parse_mode='MarkdownV2')
        else:
            await update.message.reply_text(f"❌ Failed to set label for `{safe_addr_fmt}`\\. An unexpected error occurred\\.", parse_mode='MarkdownV2')
        
        context.user_data.clear()
        return ConversationHandler.END

    async def cancel_label_wallet_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        reply_text = "Labeling wallet process cancelled."
        if update.message: await update.message.reply_text(reply_text)
        elif update.callback_query:
            await update.callback_query.answer()
            try: await update.callback_query.edit_message_text(text=reply_text)
            except Exception: await context.bot.send_message(chat_id=update.callback_query.message.chat_id, text=reply_text)
        context.user_data.clear()
        return ConversationHandler.END
    # --- End Label Wallet Conversation ---

    # --- List Wallets (adapted for button) ---
    async def list_wallets(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = None
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            chat_id = query.message.chat_id
            await context.bot.send_message(chat_id=chat_id, text="Fetching your wallets...")
        elif update.message:
            chat_id = update.effective_chat.id
        
        if not chat_id:
            logger.error("list_wallets called without a valid chat_id.")
            return

        wallets = await self.db.get_user_wallets(chat_id)
        if not wallets:
            message_to_send = r"You are not tracking any wallets yet\. Use the 'Add Wallet' button to start\."
            await context.bot.send_message(chat_id=chat_id, text=message_to_send, parse_mode='MarkdownV2')
            return

        message_parts = ["*Your Tracked Wallets:*"]
        for w in wallets:
            safe_addr_fmt = escape_markdown(w.address, version=2) # Use full address
            label_part = f" \\- '{escape_markdown(w.label, version=2)}'" if w.label else ""
            message_parts.append(f"\n➖ `{safe_addr_fmt}`{label_part}")
        full_message = "".join(message_parts)
        await self.notifier.send_message(chat_id, full_message, parse_mode='MarkdownV2')

    # --- Conversation Handler Getters as Static Methods ---
    @staticmethod
    def get_add_wallet_conversation_handler(handlers_instance: "WalletManagementHandlers") -> ConversationHandler:
        conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(handlers_instance.add_wallet_start, pattern=f"^{BUTTON_CALLBACK_WALLET_MENU_ADD}$")],
        states={
            ASK_WALLET_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_instance.received_wallet_address)],
            ASK_WALLET_LABEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_instance.received_wallet_label),
                CallbackQueryHandler(handlers_instance.skip_wallet_label_callback, pattern=f"^{CALLBACK_SKIP_WALLET_LABEL}$")]},
        fallbacks=[
            CommandHandler("cancel_wallet_add", handlers_instance.cancel_add_wallet_conversation), 
            CallbackQueryHandler(handlers_instance.cancel_add_wallet_conversation, pattern=f"^{CALLBACK_CANCEL_WALLET_ADD}$")],
        per_message=False, name="add_wallet_conversation")
        return conv_handler

    @staticmethod
    def get_remove_wallet_conversation_handler(handlers_instance: "WalletManagementHandlers") -> ConversationHandler:
        conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(handlers_instance.remove_wallet_start, pattern=f"^{BUTTON_CALLBACK_WALLET_MENU_REMOVE}$")],
        states={
            ASK_WALLET_TO_REMOVE_IDENTIFIER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_instance.received_wallet_to_remove_identifier)],
            CONFIRM_WALLET_REMOVAL: [
                CallbackQueryHandler(handlers_instance.confirm_remove_wallet_callback, pattern=f"^{CALLBACK_WALLET_REMOVE_CONFIRM_YES}$"),
                CallbackQueryHandler(handlers_instance.confirm_remove_wallet_callback, pattern=f"^{CALLBACK_WALLET_REMOVE_CONFIRM_NO}$")]},
        fallbacks=[
            CommandHandler("cancel_wallet_remove", handlers_instance.cancel_remove_wallet_conversation),
            CallbackQueryHandler(handlers_instance.cancel_remove_wallet_conversation, pattern=f"^{CALLBACK_CANCEL_WALLET_REMOVE}$")],
        per_message=False, name="remove_wallet_conversation")
        return conv_handler

    @staticmethod
    def get_label_wallet_conversation_handler(handlers_instance: "WalletManagementHandlers") -> ConversationHandler:
        conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(handlers_instance.label_wallet_start, pattern=f"^{BUTTON_CALLBACK_WALLET_MENU_LABEL}$")],
        states={
            ASK_WALLET_TO_LABEL_IDENTIFIER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_instance.received_wallet_to_label_identifier)],
            ASK_NEW_WALLET_LABEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_instance.received_new_wallet_label)]},
        fallbacks=[
            CommandHandler("cancel_wallet_label", handlers_instance.cancel_label_wallet_conversation),
            CallbackQueryHandler(handlers_instance.cancel_label_wallet_conversation, pattern=f"^{CALLBACK_CANCEL_WALLET_LABEL}$")],
        per_message=False, name="label_wallet_conversation")
        return conv_handler
