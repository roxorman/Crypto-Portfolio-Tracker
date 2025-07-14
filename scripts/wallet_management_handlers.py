# wallet_management_handlers.py
from telegram import Update
from telegram.ext import ContextTypes
from db_manager import DatabaseManager
from notifier import Notifier
from config import Config
from utils import format_address
from telegram.helpers import escape_markdown
import logging
from typing import Optional

from telegram.ext import ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from wallet_manager import WalletManager
from core_handlers import CALLBACK_MAIN_MENU_WALLETS, CoreHandlers

logger = logging.getLogger(__name__)

# Conversation states for adding a wallet
ASK_WALLET_ADDRESS, ASK_WALLET_LABEL = range(2)
# Conversation states for labeling a wallet (ensure unique range)
ASK_WALLET_TO_LABEL_IDENTIFIER, ASK_NEW_WALLET_LABEL = range(ASK_WALLET_LABEL + 1, ASK_WALLET_LABEL + 3)

# Callback data
CALLBACK_SKIP_WALLET_LABEL = "skip_wallet_label"
CALLBACK_CANCEL_WALLET_ADD = "cancel_wallet_add"
CALLBACK_CANCEL_WALLET_LABEL = "cancel_wallet_label"
CALLBACK_REMOVE_WALLET_PREFIX = "rm_wallet_id:" # Prefix for delete buttons

# Button patterns (must match core_handlers.py)
BUTTON_CALLBACK_WALLET_MENU_ADD = "wallet_menu_add"
BUTTON_CALLBACK_WALLET_MENU_REMOVE = "wallet_menu_remove"
BUTTON_CALLBACK_WALLET_MENU_LABEL = "wallet_menu_label"

class WalletManagementHandlers:
    def __init__(self, db_manager: DatabaseManager, notifier: Notifier, wallet_manager: WalletManager, config: Config, core_handlers: "CoreHandlers"):
        self.db = db_manager
        self.notifier = notifier
        self.wallet_manager = wallet_manager
        self.config = config
        self.core_handlers = core_handlers
        logger.info("WalletManagementHandlers initialized.")
        
    async def start_add_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Entry point for the Add Wallet button."""
        return await self.add_wallet_start(update, context)
        
    async def start_remove_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Entry point for the Remove Wallet button. Now shows a menu."""
        await self.remove_wallet_start(update, context)
        
    async def start_label_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Entry point for the Label Wallet button."""
        return await self.label_wallet_start(update, context)

    # --- Remove Wallet Flow (Button-based, no longer a Conversation) ---
    async def remove_wallet_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Displays a menu of wallets for the user to select for deletion."""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id

        wallets = await self.db.get_user_wallets(user_id)

        if not wallets:
            keyboard = [[InlineKeyboardButton("⬅️ Back to Wallet Menu", callback_data=CALLBACK_MAIN_MENU_WALLETS)]]
            await query.edit_message_text(
                text="You have no wallets to remove.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        keyboard = []
        for wallet in wallets:
            # Button text is the label or the formatted address if no label
            button_text = f"🗑️ {wallet.label or format_address(wallet.address)}"
            # Callback data includes the prefix and the wallet's database ID
            callback_data = f"{CALLBACK_REMOVE_WALLET_PREFIX}{wallet.wallet_id}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
        # Add a "Back" button to return to the main wallet management menu
        keyboard.append([InlineKeyboardButton("⬅️ Back to Wallet Menu", callback_data=CALLBACK_MAIN_MENU_WALLETS)])
        
        await query.edit_message_text(
            text="Select a wallet to remove:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def handle_remove_wallet_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles the button press to delete a specific wallet."""
        query = update.callback_query
        user_id = query.from_user.id
        
        try:
            # Extract the wallet ID from the callback data "rm_wallet_id:123"
            wallet_id_to_delete = int(query.data.split(':')[1])
        except (IndexError, ValueError):
            await query.answer("Error: Invalid wallet selection.", show_alert=True)
            return
            
        # Perform the deletion
        success = await self.db.delete_wallet_identity(user_id=user_id, wallet_id=wallet_id_to_delete)
        
        if success:
            await query.answer("✅ Wallet removed successfully.", show_alert=True)
        else:
            # This could happen if the wallet was deleted in another session, or a permission error
            await query.answer("❌ Error removing wallet. It may no longer exist.", show_alert=True)

        # After deletion, refresh the list of wallets to remove by calling the start function again
        # This will edit the existing message with the updated list
        await self.remove_wallet_start(update, context)

    # --- Add Wallet Conversation ---
    async def add_wallet_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user_id = update.effective_user.id
        
        # --- NEW LIMIT CHECK ---
        user, _ = await self.db.create_user(user_id) # Ensures user exists, unpack the tuple
        tier_config = self.config.get_user_tier_config(user.is_premium)
        current_wallets = await self.db.get_user_wallets(user_id)
        
        if len(current_wallets) >= tier_config["MAX_WALLETS"]:
            query = update.callback_query
            await query.answer()
            await query.edit_message_text(
                f"You have reached your limit of {tier_config['MAX_WALLETS']} tracked wallets. "
                "Please remove a wallet or upgrade to Premium to add more."
            )
            return ConversationHandler.END
        # --- END LIMIT CHECK ---
        context.user_data.clear() 
        context.user_data['new_wallet_info'] = {}
        text = "Please send me the wallet address you'd like to add."
        query = update.callback_query
        await query.answer()
        await context.bot.send_message(chat_id=query.message.chat_id, text=text)
        return ASK_WALLET_ADDRESS

    async def received_wallet_address(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        address = update.message.text.strip()
        user_id = update.effective_user.id

        is_valid = await self.wallet_manager.validate_address(address)
        if not is_valid:
            await update.message.reply_text("That doesn't look like a valid wallet address. Please try again, or type /cancel_wallet_add to stop.")
            return ASK_WALLET_ADDRESS

        addr_type = await self.wallet_manager.get_address_type(address)
        
        # --- NEW LOGIC: Check if address is EVM ---
        if addr_type != "evm":
            await update.message.reply_text(
                "Currently, only EVM addresses are supported for full tracking. "
                "Solana support is coming soon! Please enter an EVM address or type /cancel_wallet_add to stop."
            )
            return ASK_WALLET_ADDRESS
        # --- END NEW LOGIC ---

        norm_address = address.lower() # Since it's confirmed EVM
        
        existing_wallet = await self.db.get_wallet_by_address(user_id, norm_address)
        if existing_wallet:
            safe_addr_fmt = escape_markdown(format_address(norm_address), version=2)
            await update.message.reply_text(
                rf"ℹ️ Wallet `{safe_addr_fmt}` is already being tracked\.",
                parse_mode='MarkdownV2')
            context.user_data.clear()
            return ConversationHandler.END

        context.user_data['new_wallet_info'] = {'address': norm_address}
        
        keyboard = [[InlineKeyboardButton("Skip Label", callback_data=CALLBACK_SKIP_WALLET_LABEL)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            rf"Got it\. Now, optionally send me a label for this wallet \(e\.g\., 'My Main Wallet'\)\.",
            reply_markup=reply_markup, parse_mode='MarkdownV2')
        return ASK_WALLET_LABEL

    async def _finalize_add_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE, label: Optional[str]) -> int:
        user_id = update.effective_user.id
        address = context.user_data['new_wallet_info']['address']
        safe_addr_fmt = escape_markdown(format_address(address), version=2)
        if label:
            if await self.db.check_label_exists(user_id, label):
                safe_label = escape_markdown(label, version=2)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=rf"❌ Failed: Another wallet already has the label '{safe_label}'\. Please try a different label\.",
                    parse_mode='MarkdownV2')
                return ASK_WALLET_LABEL
        new_wallet = await self.db.add_wallet_identity(user_id, address, label)
        reply_text_final = f"✅ Wallet `{safe_addr_fmt}` added" + (f" with label '{escape_markdown(label, version=2)}'" if label else "") + r"\." if new_wallet else f"❌ Failed to add wallet `{safe_addr_fmt}`\\."
        
        if update.callback_query: 
            await update.callback_query.edit_message_text(text=reply_text_final, parse_mode='MarkdownV2')
        else: 
            await update.message.reply_text(text=reply_text_final, parse_mode='MarkdownV2')
        
        context.user_data.clear()
        await self.core_handlers.show_wallet_menu(update, context)
        return ConversationHandler.END

    async def received_wallet_label(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        label = update.message.text.strip()
        if len(label) > 50:
            await update.message.reply_text("Label is too long (max 50 characters). Please try a shorter one.")
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
            await update.callback_query.edit_message_text(text=reply_text)
        context.user_data.clear()
        await self.core_handlers.show_wallet_menu(update, context)
        return ConversationHandler.END
    # --- End Add Wallet Conversation ---

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
        safe_addr_fmt = escape_markdown(format_address(wallet.address), version=2)
        current_label_text = f" \\(Current label: '{escape_markdown(wallet.label, version=2)}'\\)" if wallet.label else " \\(Currently unlabelled\\)"
        
        await update.message.reply_text(f"Found wallet: `{safe_addr_fmt}`{current_label_text}\\. What is the new label?", parse_mode='MarkdownV2')
        return ASK_NEW_WALLET_LABEL

    async def received_new_wallet_label(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        new_label = update.message.text.strip()
        user_id = update.effective_user.id
        wallet_id = context.user_data['label_wallet_info']['wallet_id']
        address = context.user_data['label_wallet_info']['address']
        safe_addr_fmt = escape_markdown(format_address(address), version=2)

        if len(new_label) > 50:
            await update.message.reply_text("Label is too long (max 50 characters). Please try a shorter one.")
            return ASK_NEW_WALLET_LABEL
        
        if await self.db.check_label_exists(user_id, new_label, exclude_wallet_id=wallet_id):
            safe_new_label = escape_markdown(new_label, version=2)
            await update.message.reply_text(f"❌ Failed: The label '{safe_new_label}' is already in use\\. Please try again\\.", parse_mode='MarkdownV2')
            return ASK_NEW_WALLET_LABEL

        success = await self.db.update_wallet_label(user_id, address, new_label)
        safe_new_label_fmt = escape_markdown(new_label, version=2)
        if success:
            await update.message.reply_text(f"✏️ Label for `{safe_addr_fmt}` set to '{safe_new_label_fmt}'\\.", parse_mode='MarkdownV2')
        else:
            await update.message.reply_text(f"❌ Failed to set label for `{safe_addr_fmt}`\\.", parse_mode='MarkdownV2')
        
        context.user_data.clear()
        await self.core_handlers.show_wallet_menu(update, context)
        return ConversationHandler.END

    async def cancel_label_wallet_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        reply_text = "Labeling wallet process cancelled."
        if update.message: await update.message.reply_text(reply_text)
        elif update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(text=reply_text)
        context.user_data.clear()
        await self.core_handlers.show_wallet_menu(update, context)
        return ConversationHandler.END
    # --- End Label Wallet Conversation ---

    # --- List Wallets (adapted for button) ---
    async def list_wallets(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        await context.bot.send_message(chat_id=chat_id, text="Fetching your wallets...")

        wallets = await self.db.get_user_wallets(chat_id)
        if not wallets:
            message_to_send = r"You are not tracking any wallets yet\. Use the 'Add Wallet' button to start\."
            await context.bot.send_message(chat_id=chat_id, text=message_to_send, parse_mode='MarkdownV2')
            return

        message_parts = ["*Your Tracked Wallets:*"]
        for w in wallets:
            safe_addr_fmt = escape_markdown(w.address, version=2)
            label_part = f" \\- '{escape_markdown(w.label, version=2)}'" if w.label else ""
            message_parts.append(f"\n➖ `{safe_addr_fmt}`{label_part}")
        full_message = "".join(message_parts)
        await self.notifier.send_message(chat_id, full_message, parse_mode='MarkdownV2')

    # --- Conversation Handler Getters as Static Methods ---
    @staticmethod
    def get_add_wallet_conversation_handler(handlers_instance: "WalletManagementHandlers") -> ConversationHandler:
        return ConversationHandler(
            entry_points=[CallbackQueryHandler(handlers_instance.add_wallet_start, pattern=f"^{BUTTON_CALLBACK_WALLET_MENU_ADD}$")],
            states={
                ASK_WALLET_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_instance.received_wallet_address)],
                ASK_WALLET_LABEL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_instance.received_wallet_label),
                    CallbackQueryHandler(handlers_instance.skip_wallet_label_callback, pattern=f"^{CALLBACK_SKIP_WALLET_LABEL}$")
                ]
            },
            fallbacks=[
                CommandHandler("cancel_wallet_add", handlers_instance.cancel_add_wallet_conversation),
                CallbackQueryHandler(handlers_instance.cancel_add_wallet_conversation, pattern=f"^{CALLBACK_CANCEL_WALLET_ADD}$")
            ],
            per_message=False, name="add_wallet_conversation")

    @staticmethod
    def get_label_wallet_conversation_handler(handlers_instance: "WalletManagementHandlers") -> ConversationHandler:
        return ConversationHandler(
            entry_points=[CallbackQueryHandler(handlers_instance.label_wallet_start, pattern=f"^{BUTTON_CALLBACK_WALLET_MENU_LABEL}$")],
            states={
                ASK_WALLET_TO_LABEL_IDENTIFIER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_instance.received_wallet_to_label_identifier)],
                ASK_NEW_WALLET_LABEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_instance.received_new_wallet_label)]
            },
            fallbacks=[
                CommandHandler("cancel_wallet_label", handlers_instance.cancel_label_wallet_conversation),
                CallbackQueryHandler(handlers_instance.cancel_label_wallet_conversation, pattern=f"^{CALLBACK_CANCEL_WALLET_LABEL}$")
            ],
            per_message=False, name="label_wallet_conversation")
