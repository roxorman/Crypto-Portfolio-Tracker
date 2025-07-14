# view_handlers.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup # Added
from telegram.ext import ContextTypes
from db_manager import DatabaseManager
from api_fetcher import PortfolioFetcher
from notifier import Notifier
from portfolio_analyzer import PortfolioAnalyzer
from utils import format_address, parse_view_args, split_message
from telegram.helpers import escape_markdown
import logging
from typing import List, Dict, Optional, Tuple, Any
import asyncio
from datetime  import datetime

# Import constants from core_handlers for callback data
from core_handlers import CALLBACK_VIEW_HOLDINGS_BACK_MAIN, CALLBACK_VIEW_HOLDINGS_SELECT_PREFIX # Added

# Import the decorator
from decorators import api_rate_limit
from config import Config

logger = logging.getLogger(__name__)

# Callback data constant prefixes
CALLBACK_SELECT_VIEW_TYPE_PREFIX = "select_view_type:"

class ViewHandlers:
    def __init__(self, db_manager: DatabaseManager, portfolio_fetcher: PortfolioFetcher,
                 portfolio_analyzer: PortfolioAnalyzer, notifier: Notifier, config: Config):
        self.db = db_manager
        self.portfolio_fetcher = portfolio_fetcher
        self.portfolio_analyzer = portfolio_analyzer
        self.notifier = notifier
        self.config = config
        logger.info("ViewHandlers initialized.")

    async def show_view_holdings_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Presents the initial choice between Summary and Detailed view."""
        query = update.callback_query
        logger.info(f"show_view_holdings_menu called, presenting view type choice.")
        await query.answer()

        text = (
            "Select the type of holdings view:\n\n"
            "1\\. 📊 *Summary View*: Provides a high\\-level overview of your wallet's value and holdings\\.\n"
            "2\\. 📋 *Detailed View*: Displays detailed information about each asset in your wallet for the top 100 tokens in your wallet\\.\n\n"
        )

        keyboard = [
            [InlineKeyboardButton("📊 Summary View", callback_data=f"{CALLBACK_SELECT_VIEW_TYPE_PREFIX}summary")],
            [InlineKeyboardButton("📋 Detailed View", callback_data=f"{CALLBACK_SELECT_VIEW_TYPE_PREFIX}detailed")],
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data=CALLBACK_VIEW_HOLDINGS_BACK_MAIN)],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode='MarkdownV2'
        )

    async def handle_view_type_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """After user selects a view type, this shows the list of wallets."""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id

        # Extract view_type from "select_view_type:summary"
        view_type = query.data.split(':')[1]
        
        wallets = await self.db.get_user_wallets(user_id)
        if not wallets:
            await query.edit_message_text(
                text="You don't have any wallets to view\\. Please add one from the 'Wallets' menu first\\.",
                parse_mode='MarkdownV2'
            )
            return

        keyboard = []
        for w in wallets:
            button_text = f"👛 {w.label or format_address(w.address)}"
            # Embed the view_type and wallet_id in the callback data
            callback_data = f"{CALLBACK_VIEW_HOLDINGS_SELECT_PREFIX}{view_type}:w_{w.wallet_id}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
        # Add a back button to return to the view type selection
        keyboard.append([InlineKeyboardButton("⬅️ Back to View Type", callback_data="main_menu_view_holdings")])

        text = f"Select a wallet for the *{view_type.capitalize()} View*:"
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='MarkdownV2')

    @api_rate_limit
    async def handle_view_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles the final wallet selection to generate and display the chosen view."""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        # Expected format: "vh_select:summary:w_123"
        parts = query.data.split(':')
        if len(parts) != 3:
            logger.error(f"Invalid callback data for view selection: {query.data}")
            await query.edit_message_text("❌ Invalid selection. Please try again.")
            return

        view_type, item_info = parts[1], parts[2]
        item_type = item_info[0]
        
        try:
            item_id = int(item_info[2:])
        except (ValueError, IndexError):
            await query.edit_message_text("❌ Invalid selection format. Please try again.")
            return
            
        if item_type != 'w':
            await query.edit_message_text("❌ Portfolio views are not supported in this flow. Please select a wallet.")
            return

        wallet = await self.db.get_wallet_by_id(item_id)
        if not wallet or wallet.user_id != user_id:
            await query.edit_message_text("❌ Wallet not found or does not belong to you.")
            return

        address = wallet.address
        await query.edit_message_text(
            text=f"⏳ Fetching *{view_type} view* for `{escape_markdown(format_address(address), version=2)}`\\.\\.\\.",
            parse_mode='MarkdownV2'
        )

        message_text = "An unexpected error occurred."
        try:
            if view_type == 'summary':
                summary_data = await self.portfolio_fetcher.fetch_zerion_wallet_summary(address)
                if summary_data:
                    message_text = self.portfolio_analyzer.format_zerion_summary_message(
                        summary_data, wallet.label, address
                    )
                else:
                    message_text = "❌ Could not fetch wallet summary from Zerion."

            elif view_type == 'detailed':
                positions = await self.portfolio_fetcher.fetch_zerion_portfolio_data(address)
                if positions is not None:
                    processed_data = self.portfolio_analyzer.process_zerion_data(positions)
                    message_text = self.portfolio_analyzer.format_zerion_holdings_message(
                        processed_data, wallet.label, address
                    )
                else:
                    message_text = "❌ Could not fetch detailed holdings from Zerion\\."
            else:
                message_text = "❌ Unknown view type selected\\."

        except Exception as e:
            logger.exception(f"Error generating view for wallet {address}: {e}")
            message_text = f"❌ An error occurred while generating the {view_type} view\\."
            
        # Final message edit with the result, no more buttons needed in this final step.
        
        # Split the message into chunks
        message_chunks = split_message(message_text)
        
        # Send the first chunk as an edit to the existing message
        await query.edit_message_text(
            text=message_chunks[0],
            parse_mode='MarkdownV2',
            reply_markup=None
        )
        
        # If there are more chunks, send them as new messages
        if len(message_chunks) > 1:
            for chunk in message_chunks[1:]:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=chunk,
                    parse_mode='MarkdownV2'
                )

    async def view_holdings(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles the /view command. Now defers to the button-based flow.
        """
        # Create a fake Update object to call the button handler
        fake_query = type('Query', (), {'data': 'main_menu_view_holdings', 'answer': (lambda: asyncio.sleep(0)), 'edit_message_text': update.message.reply_text})
        fake_update = type('Update', (), {'callback_query': fake_query, 'effective_user': update.effective_user})
        await self.show_view_holdings_menu(fake_update, context)

    async def handle_pnl_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles the PnL button press from the main menu.
        Shows a list of wallets for the user to select for viewing PnL data.
        """
        query = update.callback_query
        logger.info(f"handle_pnl_button called with callback data: {query.data}")
        await query.answer()
        user_id = query.from_user.id
        
        # Get user's wallets
        wallets = await self.db.get_user_wallets(user_id)
        
        if not wallets:
            await query.edit_message_text(
                text="You don't have any wallets added yet\\. Please add a wallet first using the Wallets menu\\.",
                parse_mode='MarkdownV2'
            )
            return
        
        # Create keyboard with wallet buttons
        keyboard = []
        for wallet in wallets:
            button_text = f"👛 {wallet.label or format_address(wallet.address)}"
            # We'll use a special callback data format that includes the wallet address
            callback_data = f"pnl_wallet:{wallet.address}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
        # Add back button
        keyboard.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data=CALLBACK_VIEW_HOLDINGS_BACK_MAIN)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            text="Select a wallet to view its PnL statistics:",
            reply_markup=reply_markup
        )
    
    @api_rate_limit
    async def handle_pnl_wallet_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles the selection of a wallet from the PnL wallet selection menu.
        """
        query = update.callback_query
        logger.info(f"handle_pnl_wallet_selection called with callback data: {query.data}")
        await query.answer()
        
        # Extract wallet address from callback data
        wallet_address = query.data.split(':')[1]
        logger.info(f"Extracted wallet address: {wallet_address}")
        
        # Set up context.args for view_pnl_stats
        context.args = [wallet_address]
        
        # Edit message to show loading
        formatted_address = format_address(wallet_address)
        escaped_address = escape_markdown(formatted_address, version=2)
        await query.edit_message_text(
            text=f"⏳ Fetching PnL data for wallet `{escaped_address}`\\.\\.\\.",
            parse_mode='MarkdownV2'
        )
        
        # Call view_pnl_stats with the wallet address
        await self.view_pnl_stats(update, context)
    
    async def view_pnl_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Fetches and displays profit and loss (PnL) statistics for a wallet address.
        Currently supports single wallet addresses only, not portfolios.
        """
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        args = context.args
        
        if not args or len(args) == 0:
            # Use context.bot.send_message for consistency if this is ever called from a non-command context
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "Usage: /pnl \\<Address \\| Label\\> [chain:\\<ChainName\\>]\n"
                    "Example: `/pnl 0x123...abc`\n"
                    "Example: `/pnl MyWalletLabel`\n"
                    "Example: `/pnl 0xabc...def chain:ethereum`"
                ), 
                parse_mode='MarkdownV2'
            )
            return
        
        identifier, chain_filter = parse_view_args(args)
        safe_id = escape_markdown(identifier, version=2)
        safe_chain_filter_msg = escape_markdown(chain_filter, version=2) if chain_filter else "All Chains"
        
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"⏳ Fetching PnL data for `{safe_id}` \\({safe_chain_filter_msg}\\)\\.\\.\\.", 
            parse_mode='MarkdownV2'
        )
        
        # Find the wallet by address or label
        target_wallet = await self.db.find_user_wallet(user_id, identifier)
        
        if not target_wallet:
            await context.bot.send_message(
                chat_id=chat_id, 
                text=f"❌ Wallet '{safe_id}' not found\\. Please provide a valid wallet address or label\\.", 
                parse_mode='MarkdownV2'
            )
            return
        
        # Check if the wallet address is a Solana address (starts with a different format than EVM addresses)
        if not target_wallet.address.startswith('0x'):
            await context.bot.send_message(
                chat_id=chat_id, 
                text=f"❌ PnL data is only available for EVM wallets\\. The wallet '{safe_id}' appears to be a non\\-EVM address \\(e\\.g\\., Solana\\)\\.", 
                parse_mode='MarkdownV2'
            )
            return
        
        # Convert chain filter to Zerion format if provided
        chains_filter = [chain_filter] if chain_filter else None
        
        # Check if the chain filter is for a non-EVM chain
        non_evm_chains = ['solana', 'sol', 'bitcoin', 'btc']
        if chain_filter and chain_filter.lower() in non_evm_chains:
            await context.bot.send_message(
                chat_id=chat_id, 
                text=f"❌ PnL data is only available for EVM chains\\. The specified chain '{safe_chain_filter_msg}' is not supported\\.", 
                parse_mode='MarkdownV2'
            )
            return
        
        try:
            # Fetch PnL data from Zerion
            pnl_data = await self.portfolio_fetcher.zerion_pnl_data(
                evm_address=target_wallet.address,
                chains_filter=chains_filter
            )
            
            if not pnl_data or 'data' not in pnl_data or 'attributes' not in pnl_data['data']:
                await context.bot.send_message(
                    chat_id=chat_id, 
                    text=f"❌ No PnL data available for wallet '{safe_id}'\\. The wallet may be new or have no transaction history\\.", 
                    parse_mode='MarkdownV2'
                )
                return
        except Exception as e:
            logger.error(f"Error fetching PnL data for {target_wallet.address}: {e}")
            await context.bot.send_message(
                chat_id=chat_id, 
                text=f"❌ Error fetching PnL data for wallet '{safe_id}'\\. This may be due to an API issue or unsupported chain\\.", 
                parse_mode='MarkdownV2'
            )
            return
        
        # Extract PnL attributes
        attributes = pnl_data['data']['attributes']
        
        # Format the message with PnL data
        wallet_label = target_wallet.label or format_address(target_wallet.address)
        safe_wallet_label = escape_markdown(wallet_label, version=2)
        
        # Format currency values with commas and 2 decimal places
        realized_gain = attributes.get('realized_gain', 0)
        unrealized_gain = attributes.get('unrealized_gain', 0)
        total_fee = attributes.get('total_fee', 0)
        net_invested = attributes.get('net_invested', 0)
        received_external = attributes.get('received_external', 0)
        sent_external = attributes.get('sent_external', 0)
        sent_for_nfts = attributes.get('sent_for_nfts', 0)
        received_for_nfts = attributes.get('received_for_nfts', 0)
        
        # Calculate total gain/loss
        total_gain_loss = realized_gain + unrealized_gain
        
        # Format the message
        message_parts = [
            f"📊 *PnL Analysis for {safe_wallet_label}*",
            f"",
            f"💰 *Total Gain/Loss:* ${escape_markdown(f'{total_gain_loss:,.2f}', version=2)}",
            f"",
            f"*Realized Gain:* ${escape_markdown(f'{realized_gain:,.2f}', version=2)}",
            f"*Unrealized Gain:* ${escape_markdown(f'{unrealized_gain:,.2f}', version=2)}",
            f"*Total Fees Paid:* ${escape_markdown(f'{total_fee:,.2f}', version=2)}",
            f"",
            f"*Net Invested:* ${escape_markdown(f'{net_invested:,.2f}', version=2)}",
            f"*Received External:* ${escape_markdown(f'{received_external:,.2f}', version=2)}",
            f"*Sent External:* ${escape_markdown(f'{sent_external:,.2f}', version=2)}",
            f"",
            f"*NFT Activity:*",
            f"  *Sent for NFTs:* ${escape_markdown(f'{sent_for_nfts:,.2f}', version=2)}",
            f"  *Received for NFTs:* ${escape_markdown(f'{received_for_nfts:,.2f}', version=2)}",
        ]
        
        # Add chain filter info if provided
        if chain_filter:
            message_parts.append(f"")
            message_parts.append(f"_Data filtered for chain: {safe_chain_filter_msg}_")
        
        formatted_message = "\n".join(message_parts)
        
        # Send the formatted message
        await self.notifier.send_message(user_id, formatted_message, parse_mode='MarkdownV2')

def format_transaction_summary(summary: dict, operation_type: str, wallet_nickname: str) -> str:
    """
    Formats the transaction analysis summary into a neat MarkdownV2 message for Telegram.
    """
    if isinstance(summary, str):
        # If the summary itself is a string (e.g., an error message), just escape and return
        return escape_markdown(summary, version=2)

    # Escape content that will be placed inside the bold tags or code blocks
    wallet_nickname_md = escape_markdown(wallet_nickname, version=2)
    operation_type_md = escape_markdown(operation_type.capitalize(), version=2)

    # Use single asterisks * for bolding in MarkdownV2
    # Ensure only the content *inside* the bold tags is escaped
    message = [f"🔎 *Transaction Analysis for {wallet_nickname_md}*"]
    message.append(f"*Type:* `{operation_type_md}`")
    message.append(f"*Total Transactions:* `{summary['total_transactions']}`")

    # Date Range
    if summary['date_range']['start'] and summary['date_range']['end']:
        start_date = escape_markdown(
            datetime.fromisoformat(summary['date_range']['start']).strftime('%Y-%m-%d'),
            version=2
        )
        end_date = escape_markdown(
            datetime.fromisoformat(summary['date_range']['end']).strftime('%Y-%m-%d'),
            version=2
        )
        message.append(f"*Date Range:* `{start_date}` to `{end_date}`")

    # Total Value and Fees
    total_value_usd = f"{summary['total_value_usd']:,.2f}"
    total_fees_usd = f"{summary['total_fees_usd']:,.2f}"
    # Escape the dollar sign and the value itself
    message.append(f"*Total Value:* \\${escape_markdown(total_value_usd, version=2)}")
    message.append(f"*Total Fees:* \\${escape_markdown(total_fees_usd, version=2)}")

    # Transactions by Chain
    if summary['transactions_by_chain']:
        message.append("\n*Transactions by Chain:*")
        for chain, count in summary['transactions_by_chain'].items():
            chain_md = escape_markdown(chain, version=2)
            message.append(f"`{chain_md}`: {count}")

    # Top Senders/Recipients
    actor_label = "Recipients" if operation_type == 'send' else "Senders"
    top_by_value_key = f"top_{actor_label.lower()}_by_value"
    top_by_count_key = f"top_{actor_label.lower()}_by_count"

    if summary.get(top_by_value_key):
        message.append(f"\n*Top 5 {actor_label} by Value \\(USD\\):*")
        for actor, value in summary[top_by_value_key].items():
            value_md = escape_markdown(f"{value:,.2f}", version=2)
            message.append(f"`{actor}`: \\${value_md}")

    if summary.get(top_by_count_key):
        message.append(f"\n*Top 5 {actor_label} by Count:*")
        for actor, count in summary[top_by_count_key].items():
            message.append(f"`{actor}`: {count}")

    # Top Tokens
    token_label = "Sent" if operation_type == 'send' else "Received"
    top_tokens_key = f"top_{token_label.lower()}_tokens_usd"
    if summary.get(top_tokens_key):
        message.append(f"\n*Top 5 {token_label} Tokens by Value \\(USD\\):*")
        for token, value in summary[top_tokens_key].items():
            token_md = escape_markdown(token, version=2)
            value_md = escape_markdown(f"{value:,.2f}", version=2)
            message.append(f"`{token_md}`: \\${value_md}")

    # Additional Insights
    insights = summary.get('additional_insights', {})
    if insights:
        message.append("\n*Additional Insights:*")
        avg_value = f"{insights.get('average_transaction_value_usd', 0):,.2f}"
        message.append(f"*Average Value:* \\${escape_markdown(avg_value, version=2)}")

        if insights.get('transaction_status_distribution'):
            message.append("*Status Distribution:*")
            for status, count in insights['transaction_status_distribution'].items():
                status_md = escape_markdown(status, version=2)
                message.append(f"`{status_md}`: {count}")

    return "\n".join(message)
