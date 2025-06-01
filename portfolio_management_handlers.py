# portfolio_management_handlers.py
from telegram import Update
from telegram.ext import ContextTypes
from db_manager import DatabaseManager
from notifier import Notifier
from utils import format_address, parse_view_args # Import parse_view_args
from telegram.helpers import escape_markdown
import logging
from typing import List, Dict, Optional, Tuple, Any # For parse_view_args return type if needed

from telegram.ext import ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler # Added
from telegram import InlineKeyboardButton, InlineKeyboardMarkup # Added

logger = logging.getLogger(__name__)

# Conversation states for creating a portfolio
ASK_PORTFOLIO_NAME, ASK_PORTFOLIO_DESCRIPTION = range(2)
# Conversation states for deleting a portfolio
ASK_PORTFOLIO_TO_DELETE_NAME, CONFIRM_PORTFOLIO_DELETION = range(ASK_PORTFOLIO_DESCRIPTION + 1, ASK_PORTFOLIO_DESCRIPTION + 3)
# Conversation states for renaming a portfolio
ASK_OLD_PORTFOLIO_NAME_FOR_RENAME, ASK_NEW_PORTFOLIO_NAME_FOR_RENAME = range(CONFIRM_PORTFOLIO_DELETION + 1, CONFIRM_PORTFOLIO_DELETION + 3)
# Conversation states for adding a wallet to a portfolio
ASK_PORTFOLIO_NAME_FOR_ADD_WALLET, ASK_WALLET_ID_FOR_ADD_TO_PORTFOLIO = range(ASK_NEW_PORTFOLIO_NAME_FOR_RENAME + 1, ASK_NEW_PORTFOLIO_NAME_FOR_RENAME + 3) # States 6, 7
# Conversation states for removing a wallet from a portfolio
ASK_PORTFOLIO_NAME_FOR_REMOVE_WALLET, ASK_WALLET_ID_FOR_REMOVE_FROM_PORTFOLIO, CONFIRM_REMOVE_WALLET_FROM_PORTFOLIO = range(ASK_WALLET_ID_FOR_ADD_TO_PORTFOLIO + 1, ASK_WALLET_ID_FOR_ADD_TO_PORTFOLIO + 4) # States 8, 9, 10


# Callback data
CALLBACK_SKIP_PORTFOLIO_DESCRIPTION = "skip_portfolio_description"
CALLBACK_CANCEL_PORTFOLIO_CREATE = "cancel_portfolio_create"
CALLBACK_PORTFOLIO_DELETE_CONFIRM_YES = "p_del_confirm_yes"
CALLBACK_PORTFOLIO_DELETE_CONFIRM_NO = "p_del_confirm_no"
CALLBACK_CANCEL_PORTFOLIO_DELETE = "cancel_p_delete"
CALLBACK_CANCEL_PORTFOLIO_RENAME = "cancel_p_rename"
CALLBACK_CANCEL_PORTFOLIO_ADD_WALLET = "cancel_p_add_wallet"
CALLBACK_CANCEL_PORTFOLIO_REMOVE_WALLET = "cancel_p_remove_wallet"
CALLBACK_PORTFOLIO_REMOVE_WALLET_CONFIRM_YES = "p_remove_wallet_yes"
CALLBACK_PORTFOLIO_REMOVE_WALLET_CONFIRM_NO = "p_remove_wallet_no"


# Button patterns (must match core_handlers.py)
BUTTON_CALLBACK_PORTFOLIO_MENU_CREATE = "portfolio_menu_create"
BUTTON_CALLBACK_PORTFOLIO_MENU_DELETE = "portfolio_menu_delete"
BUTTON_CALLBACK_PORTFOLIO_MENU_RENAME = "portfolio_menu_rename"
BUTTON_CALLBACK_PORTFOLIO_MENU_ADD_WALLET = "portfolio_menu_add_wallet"
BUTTON_CALLBACK_PORTFOLIO_MENU_REMOVE_WALLET = "portfolio_menu_remove_wallet"


class PortfolioManagementHandlers:
    def __init__(self, db_manager: DatabaseManager, notifier: Notifier):
        self.db = db_manager
        self.notifier = notifier
        logger.info("PortfolioManagementHandlers initialized.")

    # --- Create Portfolio Conversation ---
    async def portfolio_create_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Starts the conversation to create a new portfolio."""
        context.user_data['new_portfolio_info'] = {}
        query = update.callback_query
        await query.answer()
        # Don't remove buttons from sub-menu, send new message for prompt
        # await query.edit_message_reply_markup(reply_markup=None) 
        await context.bot.send_message(chat_id=query.message.chat_id, text="What would you like to name your new portfolio?")
        return ASK_PORTFOLIO_NAME

    async def received_portfolio_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles receiving the portfolio name."""
        portfolio_name = update.message.text.strip()
        user_id = update.effective_user.id

        if not portfolio_name:
            await update.message.reply_text("Portfolio name cannot be empty. Please enter a name, or type /cancel\_pcreate to stop.")
            return ASK_PORTFOLIO_NAME
        if len(portfolio_name) > 100:
            await update.message.reply_text("Portfolio name is too long (max 100 characters). Please try a shorter one, or type /cancel\_pcreate to stop.")
            return ASK_PORTFOLIO_NAME

        existing_portfolio = await self.db.get_portfolio_by_name(user_id, portfolio_name)
        if existing_portfolio:
            safe_name = escape_markdown(portfolio_name, version=2)
            await update.message.reply_text(
                f"❌ You already have a portfolio named '{safe_name}'\\. Please choose a different name, or type /cancel\_pcreate to stop\\.",
                parse_mode='MarkdownV2'
            )
            return ASK_PORTFOLIO_NAME
        
        # Ensure 'new_portfolio_info' is initialized
        if 'new_portfolio_info' not in context.user_data:
            context.user_data['new_portfolio_info'] = {}
        context.user_data['new_portfolio_info']['name'] = portfolio_name
        
        keyboard = [[InlineKeyboardButton("Skip Description", callback_data=CALLBACK_SKIP_PORTFOLIO_DESCRIPTION)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Great name\! Optionally, add a short description for your portfolio, or skip this step\.",
            reply_markup=reply_markup,
            parse_mode='MarkdownV2'
        )
        return ASK_PORTFOLIO_DESCRIPTION

    async def _finalize_portfolio_creation(self, update: Update, context: ContextTypes.DEFAULT_TYPE, description: Optional[str]) -> int:
        user_id = update.effective_user.id
        name = context.user_data['new_portfolio_info']['name']
        safe_name = escape_markdown(name, version=2)

        portfolio = await self.db.create_portfolio(user_id, name, description or "")
        
        reply_text_final = ""
        if portfolio:
            reply_text_final = f"✅ Portfolio '{safe_name}' created successfully\\!"
        else:
            # This case should ideally be caught by get_portfolio_by_name check earlier
            reply_text_final = f"❌ Failed to create portfolio '{safe_name}'\\. An unexpected error occurred or it already exists\\."

        if update.callback_query and update.callback_query.data == CALLBACK_SKIP_PORTFOLIO_DESCRIPTION:
            await update.callback_query.edit_message_text(text=reply_text_final, parse_mode='MarkdownV2')
        elif update.message:
            await update.message.reply_text(text=reply_text_final, parse_mode='MarkdownV2')
        
        context.user_data.clear()
        return ConversationHandler.END

    async def received_portfolio_description(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles receiving the portfolio description."""
        description = update.message.text.strip()
        if len(description) > 255: # Assuming a max length for description
            await update.message.reply_text("Description is too long (max 255 characters). Please try a shorter one, or type /cancel\_pcreate to stop.")
            return ASK_PORTFOLIO_DESCRIPTION
        return await self._finalize_portfolio_creation(update, context, description)

    async def skip_portfolio_description_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles skipping the portfolio description."""
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text="Okay, skipping description.")
        return await self._finalize_portfolio_creation(update, context, None)

    async def cancel_portfolio_create_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancels the portfolio creation conversation."""
        reply_text = "Portfolio creation cancelled."
        if update.message: await update.message.reply_text(reply_text)
        elif update.callback_query:
            await update.callback_query.answer()
            try: await update.callback_query.edit_message_text(text=reply_text)
            except Exception: await context.bot.send_message(chat_id=update.callback_query.message.chat_id, text=reply_text)
        context.user_data.clear()
        return ConversationHandler.END
    # --- End Create Portfolio Conversation ---

    # --- Delete Portfolio Conversation ---
    async def portfolio_delete_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Starts the conversation to delete a portfolio."""
        context.user_data.clear()
        context.user_data['delete_portfolio_info'] = {}
        query = update.callback_query
        await query.answer()
        # Don't edit sub-menu message
        await context.bot.send_message(chat_id=query.message.chat_id, text="Which portfolio would you like to delete? Please send its name.")
        return ASK_PORTFOLIO_TO_DELETE_NAME

    async def received_portfolio_to_delete_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles receiving the name of the portfolio to delete."""
        portfolio_name = update.message.text.strip()
        user_id = update.effective_user.id

        portfolio_to_delete = await self.db.get_portfolio_by_name(user_id, portfolio_name)

        if not portfolio_to_delete:
            safe_name = escape_markdown(portfolio_name, version=2)
            await update.message.reply_text(
                f"❌ Portfolio '{safe_name}' not found\\. Please try a different name, or type /cancel\_pdelete to stop\\.",
                parse_mode='MarkdownV2'
            )
            return ASK_PORTFOLIO_TO_DELETE_NAME
        
        context.user_data['delete_portfolio_info']['name'] = portfolio_to_delete.name
        safe_name_fmt = escape_markdown(portfolio_to_delete.name, version=2)
        
        text = f"Found portfolio: '{safe_name_fmt}'\\.\nAre you sure you want to delete it\\? This action cannot be undone\\."
        keyboard = [
            [InlineKeyboardButton("✅ Yes, Delete", callback_data=CALLBACK_PORTFOLIO_DELETE_CONFIRM_YES)],
            [InlineKeyboardButton("❌ No, Cancel", callback_data=CALLBACK_PORTFOLIO_DELETE_CONFIRM_NO)],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')
        return CONFIRM_PORTFOLIO_DELETION

    async def confirm_portfolio_delete_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles the confirmation for deleting a portfolio."""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        if query.data == CALLBACK_PORTFOLIO_DELETE_CONFIRM_YES:
            portfolio_name = context.user_data['delete_portfolio_info']['name']
            safe_name_fmt = escape_markdown(portfolio_name, version=2)
            success = await self.db.delete_portfolio(user_id, portfolio_name)
            if success:
                await query.edit_message_text(text=f"🗑️ Portfolio '{safe_name_fmt}' deleted successfully\\.", parse_mode='MarkdownV2')
            else:
                # This might happen if it was deleted between check and confirm, though unlikely.
                await query.edit_message_text(text=f"❌ Failed to delete portfolio '{safe_name_fmt}'\\. It might have been already deleted or an error occurred\\.", parse_mode='MarkdownV2')
        elif query.data == CALLBACK_PORTFOLIO_DELETE_CONFIRM_NO:
            await query.edit_message_text(text="Portfolio deletion cancelled.")
        
        context.user_data.clear()
        return ConversationHandler.END

    async def cancel_portfolio_delete_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancels the portfolio deletion conversation."""
        reply_text = "Portfolio deletion cancelled."
        if update.message: await update.message.reply_text(reply_text)
        elif update.callback_query:
            await update.callback_query.answer()
            try: await update.callback_query.edit_message_text(text=reply_text)
            except Exception: await context.bot.send_message(chat_id=update.callback_query.message.chat_id, text=reply_text)
        context.user_data.clear()
        return ConversationHandler.END
    # --- End Delete Portfolio Conversation ---

    # --- Rename Portfolio Conversation ---
    async def portfolio_rename_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Starts the conversation to rename a portfolio."""
        context.user_data.clear()
        context.user_data['rename_portfolio_info'] = {}
        query = update.callback_query
        await query.answer()
        await context.bot.send_message(chat_id=query.message.chat_id, text="Which portfolio would you like to rename? Please send its current name.")
        return ASK_OLD_PORTFOLIO_NAME_FOR_RENAME

    async def received_old_portfolio_name_for_rename(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles receiving the old portfolio name for renaming."""
        old_name = update.message.text.strip()
        user_id = update.effective_user.id

        portfolio_to_rename = await self.db.get_portfolio_by_name(user_id, old_name)
        if not portfolio_to_rename:
            safe_old_name = escape_markdown(old_name, version=2)
            await update.message.reply_text(
                f"❌ Portfolio '{safe_old_name}' not found\\. Please try a different name, or type /cancel\_prename to stop\\.",
                parse_mode='MarkdownV2'
            )
            return ASK_OLD_PORTFOLIO_NAME_FOR_RENAME
        
        context.user_data['rename_portfolio_info']['old_name'] = old_name
        safe_old_name_fmt = escape_markdown(old_name, version=2)
        await update.message.reply_text(
            f"Found portfolio '{safe_old_name_fmt}'\\. What would you like to rename it to?",
            parse_mode='MarkdownV2'
        )
        return ASK_NEW_PORTFOLIO_NAME_FOR_RENAME

    async def received_new_portfolio_name_for_rename(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles receiving the new portfolio name and performs the rename."""
        new_name = update.message.text.strip()
        user_id = update.effective_user.id
        old_name = context.user_data['rename_portfolio_info']['old_name']

        if not new_name:
            await update.message.reply_text("New portfolio name cannot be empty. Please enter a name, or type /cancel\_prename to stop.")
            return ASK_NEW_PORTFOLIO_NAME_FOR_RENAME
        if len(new_name) > 100:
            await update.message.reply_text("New portfolio name is too long (max 100 characters). Please try a shorter one, or type /cancel\_prename to stop.")
            return ASK_NEW_PORTFOLIO_NAME_FOR_RENAME
        if new_name == old_name:
            await update.message.reply_text("The new name is the same as the old name. Please provide a different name or type /cancel\_prename to stop.")
            return ASK_NEW_PORTFOLIO_NAME_FOR_RENAME

        existing_new_name_portfolio = await self.db.get_portfolio_by_name(user_id, new_name)
        if existing_new_name_portfolio:
            safe_new_name_check = escape_markdown(new_name, version=2)
            await update.message.reply_text(
                f"❌ A portfolio named '{safe_new_name_check}' already exists\\. Please choose a different new name, or type /cancel\_prename to stop\\.",
                parse_mode='MarkdownV2'
            )
            return ASK_NEW_PORTFOLIO_NAME_FOR_RENAME

        success = await self.db.rename_portfolio(user_id, old_name, new_name)
        safe_old_name_fmt = escape_markdown(old_name, version=2)
        safe_new_name_fmt = escape_markdown(new_name, version=2)

        if success:
            await update.message.reply_text(f"✏️ Portfolio '{safe_old_name_fmt}' successfully renamed to '{safe_new_name_fmt}'\\.", parse_mode='MarkdownV2')
        else:
            # This might happen if old_name was deleted in between, or other rare db error
            await update.message.reply_text(f"❌ Failed to rename portfolio '{safe_old_name_fmt}'\\. An unexpected error occurred\\.", parse_mode='MarkdownV2')
        
        context.user_data.clear()
        return ConversationHandler.END

    async def cancel_portfolio_rename_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancels the portfolio rename conversation."""
        reply_text = "Portfolio rename cancelled."
        if update.message: await update.message.reply_text(reply_text)
        elif update.callback_query: # Should not be called by callback if no buttons in this flow yet
            await update.callback_query.answer()
            try: await update.callback_query.edit_message_text(text=reply_text)
            except Exception: await context.bot.send_message(chat_id=update.callback_query.message.chat_id, text=reply_text)
        context.user_data.clear()
        return ConversationHandler.END
    # --- End Rename Portfolio Conversation ---

    # --- Add Wallet to Portfolio Conversation ---
    async def padd_wallet_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Starts the conversation to add a wallet to a portfolio."""
        context.user_data.clear()
        context.user_data['padd_wallet_info'] = {}
        query = update.callback_query
        await query.answer()
        await context.bot.send_message(chat_id=query.message.chat_id, text="Which portfolio do you want to add a wallet to? Please send its name.")
        return ASK_PORTFOLIO_NAME_FOR_ADD_WALLET

    async def received_padd_portfolio_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles receiving the portfolio name for adding a wallet."""
        portfolio_name_input = update.message.text.strip() # User input
        user_id = update.effective_user.id

        portfolio = await self.db.get_portfolio_by_name(user_id, portfolio_name_input)
        if not portfolio:
            safe_name_input = escape_markdown(portfolio_name_input, version=2)
            await update.message.reply_text(
                f"❌ Portfolio '{safe_name_input}' not found\\. Please try a different name, or type /cancel\_padd to stop\\.",
                parse_mode='MarkdownV2'
            )
            return ASK_PORTFOLIO_NAME_FOR_ADD_WALLET
        
        context.user_data['padd_wallet_info']['portfolio_id'] = portfolio.portfolio_id
        context.user_data['padd_wallet_info']['portfolio_name_fmt'] = escape_markdown(portfolio.name, version=2) # General escape for storage
        
        # --- START CHANGE ---
        # Sanitize portfolio.name by replacing newlines before using it in an inline code block
        cleaned_portfolio_name = portfolio.name.replace('\n', ' ') 
        portfolio_name_for_code_block = escape_markdown(cleaned_portfolio_name, version=2, entity_type="code")
        # --- END CHANGE ---
        
        # For debugging, you can add these logs:
        logger.info(f"Original portfolio.name: '{portfolio.name}'")
        logger.info(f"Cleaned portfolio_name: '{cleaned_portfolio_name}'")
        logger.info(f"portfolio_name_for_code_block: '{portfolio_name_for_code_block}'")

        message_text = f"Okay, adding to portfolio `{portfolio_name_for_code_block}`\\. Now, please send the address or label of the wallet you want to add to this portfolio\\."
        logger.info(f"Attempting to send message_text (line 321): '{message_text}'")
        
        await update.message.reply_text(message_text, parse_mode='MarkdownV2') # This should be line 321
        return ASK_WALLET_ID_FOR_ADD_TO_PORTFOLIO

    async def received_padd_wallet_identifier(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles receiving the wallet identifier and adds it to the portfolio."""
        wallet_identifier = update.message.text.strip()
        user_id = update.effective_user.id
        portfolio_id = context.user_data['padd_wallet_info']['portfolio_id']
        portfolio_name_fmt = context.user_data['padd_wallet_info']['portfolio_name_fmt']

        wallet_identity = await self.db.find_user_wallet(user_id, wallet_identifier)
        if not wallet_identity:
            safe_wallet_id = escape_markdown(wallet_identifier, version=2)
            await update.message.reply_text(
                f"❌ Wallet '{safe_wallet_id}' not found in your tracked wallets\\. Use the 'Wallets' menu to add it first, or type /cancel\_padd to stop\\.",
                parse_mode='MarkdownV2'
            )
            return ASK_WALLET_ID_FOR_ADD_TO_PORTFOLIO

        success = await self.db.add_wallet_to_portfolio(portfolio_id, wallet_identity.wallet_id)
        safe_addr_fmt = escape_markdown(format_address(wallet_identity.address), version=2, entity_type="code")
        safe_label_part = f" \\(Label: '{escape_markdown(wallet_identity.label, version=2)}'\\)" if wallet_identity.label else ""

        if success:
            await update.message.reply_text(f"✅ Wallet `{safe_addr_fmt}`{safe_label_part} associated with portfolio '{portfolio_name_fmt}'\\.", parse_mode='MarkdownV2')
        else:
            # Check if already linked, as add_wallet_to_portfolio returns False if link exists
            link_exists = await self.db.check_portfolio_wallet_link(portfolio_id, wallet_identity.wallet_id)
            if link_exists:
                 await update.message.reply_text(f"ℹ️ Wallet `{safe_addr_fmt}`{safe_label_part} is already associated with portfolio '{portfolio_name_fmt}'\\.", parse_mode='MarkdownV2')
            else:
                 await update.message.reply_text(f"❌ Failed to associate wallet `{safe_addr_fmt}` with portfolio '{portfolio_name_fmt}'\\. An internal error occurred\\.", parse_mode='MarkdownV2')
        
        context.user_data.clear()
        return ConversationHandler.END

    async def cancel_padd_wallet_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancels the add wallet to portfolio conversation."""
        reply_text = "Process of adding wallet to portfolio cancelled."
        if update.message: await update.message.reply_text(reply_text)
        elif update.callback_query:
            await update.callback_query.answer()
            try: await update.callback_query.edit_message_text(text=reply_text)
            except Exception: await context.bot.send_message(chat_id=update.callback_query.message.chat_id, text=reply_text)
        context.user_data.clear()
        return ConversationHandler.END
    # --- End Add Wallet to Portfolio Conversation ---

    # --- Remove Wallet from Portfolio Conversation ---
    async def premove_wallet_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Starts the conversation to remove a wallet from a portfolio."""
        context.user_data.clear()
        context.user_data['premove_wallet_info'] = {}
        query = update.callback_query
        await query.answer()
        await context.bot.send_message(chat_id=query.message.chat_id, text="From which portfolio do you want to remove a wallet? Please send the portfolio name.")
        return ASK_PORTFOLIO_NAME_FOR_REMOVE_WALLET

    async def received_premove_portfolio_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles receiving the portfolio name for removing a wallet."""
        portfolio_name = update.message.text.strip()
        user_id = update.effective_user.id

        portfolio = await self.db.get_portfolio_by_name(user_id, portfolio_name)
        if not portfolio:
            safe_name = escape_markdown(portfolio_name, version=2)
            await update.message.reply_text(
                rf"❌ Portfolio '{safe_name}' not found\\. Please try a different name, or type /cancel\_premove to stop\\.",
                parse_mode='MarkdownV2'
            )
            return ASK_PORTFOLIO_NAME_FOR_REMOVE_WALLET
        
        context.user_data['premove_wallet_info']['portfolio_id'] = portfolio.portfolio_id
        context.user_data['premove_wallet_info']['portfolio_name_fmt'] = escape_markdown(portfolio.name, version=2)
        
        await update.message.reply_text(
            f"Okay, removing from portfolio '{context.user_data['premove_wallet_info']['portfolio_name_fmt']}'\\. "
            f"Now, please send the address or label of the wallet you want to remove from this portfolio\.",
            parse_mode='MarkdownV2'
        )
        return ASK_WALLET_ID_FOR_REMOVE_FROM_PORTFOLIO

    async def received_premove_wallet_identifier(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles receiving the wallet identifier to remove from the portfolio and asks for confirmation."""
        wallet_identifier = update.message.text.strip()
        user_id = update.effective_user.id
        portfolio_id = context.user_data['premove_wallet_info']['portfolio_id']
        portfolio_name_fmt = context.user_data['premove_wallet_info']['portfolio_name_fmt']

        wallet_identity = await self.db.find_user_wallet(user_id, wallet_identifier)
        if not wallet_identity:
            safe_wallet_id = escape_markdown(wallet_identifier, version=2)
            await update.message.reply_text(
                f"❌ Wallet '{safe_wallet_id}' not found in your tracked wallets\\. Please try again, or type /cancel\_premove to stop\\.",
                parse_mode='MarkdownV2'
            )
            return ASK_WALLET_ID_FOR_REMOVE_FROM_PORTFOLIO

        # Check if the wallet is actually associated with the portfolio
        is_linked = await self.db.check_portfolio_wallet_link(portfolio_id, wallet_identity.wallet_id)
        if not is_linked:
            safe_addr_fmt = escape_markdown(format_address(wallet_identity.address), version=2, entity_type="code")
            safe_label_part = f" \\(Label: '{escape_markdown(wallet_identity.label, version=2)}'\\)" if wallet_identity.label else ""
            await update.message.reply_text(
                f"ℹ️ Wallet `{safe_addr_fmt}`{safe_label_part} is not associated with portfolio '{portfolio_name_fmt}'\\. Nothing to remove\\. Type /cancel\_premove to stop or try another wallet.",
                parse_mode='MarkdownV2'
            )
            return ASK_WALLET_ID_FOR_REMOVE_FROM_PORTFOLIO


        context.user_data['premove_wallet_info']['wallet_id'] = wallet_identity.wallet_id
        context.user_data['premove_wallet_info']['wallet_address_fmt'] = escape_markdown(format_address(wallet_identity.address), version=2, entity_type="code")
        context.user_data['premove_wallet_info']['wallet_label_part'] = f" \\(Label: '{escape_markdown(wallet_identity.label, version=2)}'\\)" if wallet_identity.label else ""

        text = (f"Are you sure you want to remove wallet `{context.user_data['premove_wallet_info']['wallet_address_fmt']}`"
                f"{context.user_data['premove_wallet_info']['wallet_label_part']} from portfolio '{portfolio_name_fmt}'?")
        keyboard = [
            [InlineKeyboardButton("✅ Yes, Remove", callback_data=CALLBACK_PORTFOLIO_REMOVE_WALLET_CONFIRM_YES)],
            [InlineKeyboardButton("❌ No, Cancel", callback_data=CALLBACK_PORTFOLIO_REMOVE_WALLET_CONFIRM_NO)],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')
        return CONFIRM_REMOVE_WALLET_FROM_PORTFOLIO

    async def confirm_premove_wallet_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles the confirmation for removing a wallet from a portfolio."""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id # Not strictly needed for DB op if portfolio_id and wallet_id are known
        
        if query.data == CALLBACK_PORTFOLIO_REMOVE_WALLET_CONFIRM_YES:
            portfolio_id = context.user_data['premove_wallet_info']['portfolio_id']
            wallet_id = context.user_data['premove_wallet_info']['wallet_id']
            portfolio_name_fmt = context.user_data['premove_wallet_info']['portfolio_name_fmt']
            wallet_address_fmt = context.user_data['premove_wallet_info']['wallet_address_fmt']
            wallet_label_part = context.user_data['premove_wallet_info']['wallet_label_part']

            success = await self.db.remove_wallet_from_portfolio(portfolio_id, wallet_id)
            if success:
                await query.edit_message_text(text=f"➖ Wallet `{wallet_address_fmt}`{wallet_label_part} disassociated from portfolio '{portfolio_name_fmt}'\\.", parse_mode='MarkdownV2')
            else:
                 await query.edit_message_text(text=f"❌ Failed to disassociate wallet `{wallet_address_fmt}` from portfolio '{portfolio_name_fmt}'\\. An internal error occurred or it was already removed\\.", parse_mode='MarkdownV2')
        elif query.data == CALLBACK_PORTFOLIO_REMOVE_WALLET_CONFIRM_NO:
            await query.edit_message_text(text="Process of removing wallet from portfolio cancelled.")
        
        context.user_data.clear()
        return ConversationHandler.END

    async def cancel_premove_wallet_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancels the remove wallet from portfolio conversation."""
        reply_text = "Process of removing wallet from portfolio cancelled."
        if update.message: await update.message.reply_text(reply_text)
        elif update.callback_query:
            await update.callback_query.answer()
            try: await update.callback_query.edit_message_text(text=reply_text)
            except Exception: await context.bot.send_message(chat_id=update.callback_query.message.chat_id, text=reply_text)
        context.user_data.clear()
        return ConversationHandler.END
    # --- End Remove Wallet from Portfolio Conversation ---

    @staticmethod
    def get_premove_wallet_conversation_handler(handlers_instance: "PortfolioManagementHandlers") -> ConversationHandler:
        """Creates and returns the ConversationHandler for removing a wallet from a portfolio."""
        conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(handlers_instance.premove_wallet_start, pattern=f"^{BUTTON_CALLBACK_PORTFOLIO_MENU_REMOVE_WALLET}$")],
            states={
                ASK_PORTFOLIO_NAME_FOR_REMOVE_WALLET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_instance.received_premove_portfolio_name)],
                ASK_WALLET_ID_FOR_REMOVE_FROM_PORTFOLIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_instance.received_premove_wallet_identifier)],
                CONFIRM_REMOVE_WALLET_FROM_PORTFOLIO: [
                    CallbackQueryHandler(handlers_instance.confirm_premove_wallet_callback, pattern=f"^{CALLBACK_PORTFOLIO_REMOVE_WALLET_CONFIRM_YES}$"),
                    CallbackQueryHandler(handlers_instance.confirm_premove_wallet_callback, pattern=f"^{CALLBACK_PORTFOLIO_REMOVE_WALLET_CONFIRM_NO}$")
                ],
            },
            fallbacks=[
                CommandHandler("cancel_premove", handlers_instance.cancel_premove_wallet_conversation),
                CallbackQueryHandler(handlers_instance.cancel_premove_wallet_conversation, pattern=f"^{CALLBACK_CANCEL_PORTFOLIO_REMOVE_WALLET}$")
            ],
            per_message=False,
            name="premove_wallet_conversation"
        )
        return conv_handler

    @staticmethod
    def get_padd_wallet_conversation_handler(handlers_instance: "PortfolioManagementHandlers") -> ConversationHandler:
        """Creates and returns the ConversationHandler for adding a wallet to a portfolio."""
        conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(handlers_instance.padd_wallet_start, pattern=f"^{BUTTON_CALLBACK_PORTFOLIO_MENU_ADD_WALLET}$")],
            states={
                ASK_PORTFOLIO_NAME_FOR_ADD_WALLET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_instance.received_padd_portfolio_name)],
                ASK_WALLET_ID_FOR_ADD_TO_PORTFOLIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_instance.received_padd_wallet_identifier)],
            },
            fallbacks=[
                CommandHandler("cancel_padd", handlers_instance.cancel_padd_wallet_conversation),
                CallbackQueryHandler(handlers_instance.cancel_padd_wallet_conversation, pattern=f"^{CALLBACK_CANCEL_PORTFOLIO_ADD_WALLET}$")
            ],
            per_message=False,
            name="padd_wallet_conversation"
        )
        return conv_handler

    @staticmethod
    def get_rename_portfolio_conversation_handler(handlers_instance: "PortfolioManagementHandlers") -> ConversationHandler:
        """Creates and returns the ConversationHandler for renaming a portfolio."""
        conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(handlers_instance.portfolio_rename_start, pattern=f"^{BUTTON_CALLBACK_PORTFOLIO_MENU_RENAME}$")],
            states={
                ASK_OLD_PORTFOLIO_NAME_FOR_RENAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_instance.received_old_portfolio_name_for_rename)],
                ASK_NEW_PORTFOLIO_NAME_FOR_RENAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_instance.received_new_portfolio_name_for_rename)],
            },
            fallbacks=[
                CommandHandler("cancel_prename", handlers_instance.cancel_portfolio_rename_conversation),
                CallbackQueryHandler(handlers_instance.cancel_portfolio_rename_conversation, pattern=f"^{CALLBACK_CANCEL_PORTFOLIO_RENAME}$")
            ],
            per_message=False,
            name="rename_portfolio_conversation"
        )
        return conv_handler

    @staticmethod
    def get_delete_portfolio_conversation_handler(handlers_instance: "PortfolioManagementHandlers") -> ConversationHandler:
        """Creates and returns the ConversationHandler for deleting a portfolio."""
        conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(handlers_instance.portfolio_delete_start, pattern=f"^{BUTTON_CALLBACK_PORTFOLIO_MENU_DELETE}$")],
            states={
                ASK_PORTFOLIO_TO_DELETE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_instance.received_portfolio_to_delete_name)],
                CONFIRM_PORTFOLIO_DELETION: [
                    CallbackQueryHandler(handlers_instance.confirm_portfolio_delete_callback, pattern=f"^{CALLBACK_PORTFOLIO_DELETE_CONFIRM_YES}$"),
                    CallbackQueryHandler(handlers_instance.confirm_portfolio_delete_callback, pattern=f"^{CALLBACK_PORTFOLIO_DELETE_CONFIRM_NO}$")
                ],
            },
            fallbacks=[
                CommandHandler("cancel_pdelete", handlers_instance.cancel_portfolio_delete_conversation),
                CallbackQueryHandler(handlers_instance.cancel_portfolio_delete_conversation, pattern=f"^{CALLBACK_CANCEL_PORTFOLIO_DELETE}$")
            ],
            per_message=False,
            name="delete_portfolio_conversation"
        )
        return conv_handler

    @staticmethod
    def get_create_portfolio_conversation_handler(handlers_instance: "PortfolioManagementHandlers") -> ConversationHandler:
        """Creates and returns the ConversationHandler for creating a new portfolio."""
        conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(handlers_instance.portfolio_create_start, pattern=f"^{BUTTON_CALLBACK_PORTFOLIO_MENU_CREATE}$")],
            states={
                ASK_PORTFOLIO_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_instance.received_portfolio_name)],
                ASK_PORTFOLIO_DESCRIPTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_instance.received_portfolio_description),
                    CallbackQueryHandler(handlers_instance.skip_portfolio_description_callback, pattern=f"^{CALLBACK_SKIP_PORTFOLIO_DESCRIPTION}$")
                ],
            },
            fallbacks=[
                CommandHandler("cancel_pcreate", handlers_instance.cancel_portfolio_create_conversation),
                CallbackQueryHandler(handlers_instance.cancel_portfolio_create_conversation, pattern=f"^{CALLBACK_CANCEL_PORTFOLIO_CREATE}$") # If a cancel button is added to prompts
            ],
            per_message=False,
            name="create_portfolio_conversation"
        )
        return conv_handler

    async def portfolio_create(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # This is the old command handler, will be removed or adapted.
        # For now, it's superseded by the conversation flow.
        user_id = update.effective_user.id
        args = context.args
        if not args or len(args) == 0:
            await update.message.reply_text("Usage: /pcreate \\<Portfolio Name\\> [Optional Description]", parse_mode='MarkdownV2')
            return
        name = args[0]
        description = " ".join(args[1:]) if len(args) > 1 else ""
        portfolio = await self.db.create_portfolio(user_id, name, description)
        safe_name = escape_markdown(name, version=2)
        if portfolio:
            await update.message.reply_text(f"✅ Portfolio '{safe_name}' created successfully\\!", parse_mode='MarkdownV2') # Escaped !
        else:
            existing = await self.db.get_portfolio_by_name(user_id, name)
            if existing:
                await update.message.reply_text(f"❌ Failed to create portfolio. A portfolio named '{safe_name}' already exists.", parse_mode='MarkdownV2')
            else:
                await update.message.reply_text("❌ Failed to create portfolio. An unexpected error occurred.", parse_mode='MarkdownV2')

    async def portfolio_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = None
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            chat_id = query.message.chat_id
            # Don't remove keyboard from sub-menu message, send new message for status
            # try:
            #     await query.edit_message_reply_markup(reply_markup=None)
            # except Exception as e:
            #     logger.warning(f"Could not edit message reply markup in portfolio_list: {e}")
            await context.bot.send_message(chat_id=chat_id, text="Fetching your portfolios...")
        elif update.message:
            chat_id = update.effective_chat.id
        
        if not chat_id:
            logger.error("portfolio_list called without a valid chat_id.")
            return

        portfolios = await self.db.get_user_portfolios(chat_id) # Assuming user_id is chat_id

        if not portfolios:
            message_to_send = "You don't have any portfolios yet\\. Use the 'Create Portfolio' button or `/pcreate <Name>` to create one\\."
            await context.bot.send_message(chat_id=chat_id, text=message_to_send, parse_mode='MarkdownV2')
            return

        message_parts = ["📂 *Your Portfolios:*"]
        for p in portfolios:
            safe_name = escape_markdown(p.name, version=2, entity_type="code")
            portfolio_header = f"\n➖ `{safe_name}`"
            if p.description:
                portfolio_header += f" \\({escape_markdown(p.description, version=2)}\\)"
            message_parts.append(portfolio_header)

            if p.wallet_associations:
                message_parts.append("\n  *Associated Wallets:*")
                for assoc in p.wallet_associations:
                    wallet = assoc.wallet
                    if not wallet: continue
                    safe_address = escape_markdown(format_address(wallet.address), version=2, entity_type="code")
                    label_part = f" \\({escape_markdown(wallet.label, version=2)}\\)" if wallet.label else ""
                    message_parts.append(f"\n    ▫️ `{safe_address}`{label_part}")
            else:
                message_parts.append("\n  \\(No wallets associated with this portfolio\\)")
            message_parts.append("\n")

        full_message = "".join(message_parts)
        await self.notifier.send_message(chat_id, full_message, parse_mode='MarkdownV2') # Use chat_id

    async def portfolio_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # This will be refactored into a ConversationHandler later
        user_id = update.effective_user.id
        args = context.args
        if not args or len(args) != 1:
            await update.message.reply_text("Usage: /pdelete \\<PortfolioName\\>", parse_mode='MarkdownV2')
            return
        name = args[0]
        success = await self.db.delete_portfolio(user_id, name)
        safe_name = escape_markdown(name, version=2)
        if success:
            await update.message.reply_text(f"🗑️ Portfolio '{safe_name}' deleted successfully\\.", parse_mode='MarkdownV2')
        else:
            await update.message.reply_text(f"❌ Portfolio '{safe_name}' not found or could not be deleted\\.", parse_mode='MarkdownV2')

    async def portfolio_rename(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        args = context.args
        if not args or len(args) != 2:
            await update.message.reply_text("Usage: /prename \\<Old Portfolio Name\\> \\<New Portfolio Name\\>", parse_mode='MarkdownV2')
            return
        old_name, new_name = args
        success = await self.db.rename_portfolio(user_id, old_name, new_name)
        safe_old_name = escape_markdown(old_name, version=2)
        safe_new_name = escape_markdown(new_name, version=2)
        if success:
            await update.message.reply_text(f"✏️ Portfolio '{safe_old_name}' renamed to '{safe_new_name}'\\.", parse_mode='MarkdownV2')
        else:
            existing_old = await self.db.get_portfolio_by_name(user_id, old_name)
            existing_new = await self.db.get_portfolio_by_name(user_id, new_name)
            if not existing_old:
                 await update.message.reply_text(f"❌ Portfolio '{safe_old_name}' not found\\.", parse_mode='MarkdownV2')
            elif existing_new:
                 await update.message.reply_text(f"❌ Cannot rename: a portfolio named '{safe_new_name}' already exists\\.", parse_mode='MarkdownV2')
            else:
                 await update.message.reply_text(f"❌ Failed to rename portfolio '{safe_old_name}'\\. An unexpected error occurred\\.", parse_mode='MarkdownV2')

    async def portfolio_add_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        args = context.args
        if not args or len(args) < 2:
            await update.message.reply_text(
                "Usage: /padd \\<PortfolioName\\> \\<Address\\|Label\\> [chain:\\<ChainName\\>]\n"
                "Example: `/padd MyStuff 0x123...abc`\n"
                "Example: `/padd MyStuff 0xabc...def chain:base`", parse_mode='MarkdownV2')
            return

        portfolio_name = args[0]
        wallet_identifier_args = args[1:]
        identifier, chain_filter = parse_view_args(wallet_identifier_args) # Use imported function

        if not identifier:
            await update.message.reply_text(
                "Usage: /padd <PortfolioName> <Address|Label> [chain:<ChainName>]\n"
                "Example: `/padd MyStuff 0x123...abc`\n"
                "Example: `/padd MyStuff 0xabc...def chain:base`", parse_mode='MarkdownV2')
            return

        safe_pname = escape_markdown(portfolio_name, version=2)
        safe_id = escape_markdown(identifier, version=2)

        portfolio = await self.db.get_portfolio_by_name(user_id, portfolio_name)
        if not portfolio:
            await update.message.reply_text(f"❌ Portfolio '{safe_pname}' not found\\.", parse_mode='MarkdownV2')
            return

        wallet_identity = await self.db.find_user_wallet(user_id, identifier)
        if not wallet_identity:
            await update.message.reply_text(f"❌ Wallet '{safe_id}' not found in your tracked wallets\\. Use `/add` first\\.", parse_mode='MarkdownV2')
            return

        # The original code used `db.add_wallet_to_portfolio(portfolio.portfolio_id, wallet_identity.wallet_id)`
        # which doesn't use chain_filter for the association table. This seems correct for the current DB model.
        success = await self.db.add_wallet_to_portfolio(portfolio.portfolio_id, wallet_identity.wallet_id)
        safe_addr_fmt = escape_markdown(format_address(wallet_identity.address), version=2, entity_type="code")
        safe_label_part = f" \\(Label: '{escape_markdown(wallet_identity.label, version=2)}'\\)" if wallet_identity.label else ""

        if success:
            await update.message.reply_text(f"✅ Wallet `{safe_addr_fmt}`{safe_label_part} associated with portfolio '{safe_pname}'\\.", parse_mode='MarkdownV2')
        else:
            existing_link = await self.db.check_portfolio_wallet_link(portfolio.portfolio_id, wallet_identity.wallet_id)
            if existing_link:
                 await update.message.reply_text(f"ℹ️ Wallet `{safe_addr_fmt}`{safe_label_part} is already associated with portfolio '{safe_pname}'\\.", parse_mode='MarkdownV2')
            else:
                 await update.message.reply_text(f"❌ Failed to associate wallet `{safe_addr_fmt}` with portfolio '{safe_pname}'\\. An internal error occurred\\.", parse_mode='MarkdownV2')


    async def portfolio_remove_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        args = context.args
        if not args or len(args) < 2:
            await update.message.reply_text(
                "Usage: /premove \\<PortfolioName\\> \\<Address\\|Label\\> [chain:\\<ChainName\\>]\n"
                "Example: `/premove MyStuff 0x123...abc`\n"
                "Example: `/premove MyStuff 0xabc...def chain:base`", parse_mode='MarkdownV2')
            return

        portfolio_name = args[0]
        wallet_identifier_args = args[1:]
        identifier, chain_filter = parse_view_args(wallet_identifier_args) # Use imported function

        if not identifier:
            await update.message.reply_text(
                "Usage: /premove <PortfolioName> <Address|Label> [chain:<ChainName>]\n"
                "Example: `/premove MyStuff 0x123...abc`\n"
                "Example: `/premove MyStuff 0xabc...def chain:base`", parse_mode='MarkdownV2')
            return

        safe_pname = escape_markdown(portfolio_name, version=2)
        safe_id = escape_markdown(identifier, version=2)

        portfolio = await self.db.get_portfolio_by_name(user_id, portfolio_name)
        if not portfolio:
            await update.message.reply_text(f"❌ Portfolio '{safe_pname}' not found\\.", parse_mode='MarkdownV2')
            return

        wallet_identity = await self.db.find_user_wallet(user_id, identifier)
        if not wallet_identity:
            await update.message.reply_text(f"❌ Wallet identifier '{safe_id}' not found\\.", parse_mode='MarkdownV2')
            return

        # The original code used `db.remove_wallet_from_portfolio(portfolio.portfolio_id, wallet_identity.wallet_id)`
        # which doesn't use chain_filter for the association table.
        success = await self.db.remove_wallet_from_portfolio(portfolio.portfolio_id, wallet_identity.wallet_id)
        safe_addr_fmt = escape_markdown(format_address(wallet_identity.address), version=2, entity_type="code")
        safe_label_part = f" \\(Label: '{escape_markdown(wallet_identity.label, version=2)}'\\)" if wallet_identity.label else ""

        if success:
            await update.message.reply_text(f"➖ Wallet `{safe_addr_fmt}`{safe_label_part} disassociated from portfolio '{safe_pname}'\\.", parse_mode='MarkdownV2')
        else:
             link_existed = await self.db.check_portfolio_wallet_link(portfolio.portfolio_id, wallet_identity.wallet_id)
             if not link_existed:
                   await update.message.reply_text(f"❌ Wallet `{safe_addr_fmt}`{safe_label_part} was not associated with portfolio '{safe_pname}'\\.", parse_mode='MarkdownV2')
             else:
                  await update.message.reply_text(f"❌ Failed to disassociate wallet `{safe_addr_fmt}`{safe_label_part} from portfolio '{safe_pname}'\\. An internal error occurred\\.", parse_mode='MarkdownV2')
