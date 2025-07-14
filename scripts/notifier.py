from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from typing import Dict, Optional, List
from config import Config
import io
from telegram.helpers import escape_markdown
from utils import split_message
import logging

logger = logging.getLogger(__name__)

class Notifier:
    """Handles all Telegram notifications and message formatting."""

    def __init__(self):
        try:
             cfg = Config()
             self.bot = Bot(token=cfg.TELEGRAM_TOKEN)
             logger.info("Notifier initialized with Bot.")
        except Exception as e:
             logger.exception(f"ERROR initializing Notifier: {e}")
             self.bot = None

    async def send_message(self, chat_id: int, text: str,
                          reply_markup: Optional[InlineKeyboardMarkup] = None,
                          parse_mode: Optional[str] = None) -> bool:
        """Send a text message to a specific chat, allowing custom parse_mode."""
        try:
            message_chunks = split_message(text)
            for i, chunk in enumerate(message_chunks):
                # Only the last chunk should have the reply_markup
                current_reply_markup = reply_markup if i == len(message_chunks) - 1 else None
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode=parse_mode,
                    reply_markup=current_reply_markup
                )
            logger.info(f"Message sent to user {chat_id} (parse_mode={parse_mode or 'None'})")
            return True
        except Exception as e:
            logger.error(f"Error sending message (parse_mode={parse_mode or 'None'}): {e}")
            return False

    async def send_welcome_message(self, chat_id: int, first_name: str):
        """Sends the initial welcome message (plain text)."""
        if not self.bot: return
        # Keep welcome message plain text for simplicity
        text = f"👋 Welcome {first_name}! Bot is starting up.\nUse /help for commands."
        try:
            # Explicitly send welcome as plain text (parse_mode=None)
            await self.send_message(chat_id=chat_id, text=text, parse_mode=None)
            logger.info(f"Sent welcome message to {chat_id}")
        except Exception as e:
            logger.error(f"Error sending welcome message: {e}")

    async def send_help_message(self, chat_id: int):
        """Sends the help text (tries HTML)."""
        if not self.bot:
            return
        try:
            with open("resources/help_text.txt", "r", encoding="utf-8") as f:
                help_text = f.read()
            # Assuming help_text.txt might contain formatting, try sending as HTML
            # If help_text.txt causes errors, change parse_mode to None here.
            await self.send_message(chat_id=chat_id, text=help_text, parse_mode='HTML')

        except Exception as e:
            logger.error(f"Error sending help message: {e}")
            # Fallback to plain text if Markdown fails? Or just log the error.
            # await self.send_message(chat_id=chat_id, text=help_text, parse_mode=None)

    async def send_portfolio_summary(self, chat_id: int, portfolio_data: Dict) -> bool:
        """Send formatted portfolio summary message (caller specifies parse_mode)."""
        try:
            # Formatting happens before this call, just pass the message through
            message = self._format_portfolio_summary(portfolio_data) # This is plain text formatting
            # Let the caller (e.g., bot_handlers) decide the parse_mode
            return await self.send_message(chat_id, message)
        except Exception as e:
            logger.error(f"Error sending portfolio summary: {e}")
            return False

    async def send_wallet_summary(self, chat_id: int, wallet_data: Dict) -> bool:
        """Send formatted wallet summary message (caller specifies parse_mode)."""
        try:
             # Formatting happens before this call, just pass the message through
            message = self._format_wallet_summary(wallet_data) # This is plain text formatting
            # Let the caller (e.g., bot_handlers) decide the parse_mode
            return await self.send_message(chat_id, message)
        except Exception as e:
            logger.error(f"Error sending wallet summary: {e}")
            return False

    async def send_alert_notification(self, chat_id: int, message: str, parse_mode: str = "MarkdownV2", reply_markup: Optional[InlineKeyboardMarkup] = None) -> bool:
        """
        Send alert notification message.
        Defaults to MarkdownV2 for richer formatting.
        The caller is responsible for crafting the full message content.
        """
        try:
            # The message is now expected to be fully formatted by the caller.
            # The "🚨 ALERT 🚨" prefix or similar should be part of the 'message' argument if desired.
            return await self.send_message(chat_id, message, parse_mode=parse_mode, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error sending alert notification (parse_mode={parse_mode}): {e}")
            return False

    async def send_chart(self, chat_id: int, chart_data: io.BytesIO,
                        caption: Optional[str] = None) -> bool:
        """Send a chart image to a specific chat (caption is plain text)."""
        try:
            await self.bot.send_photo(
                chat_id=chat_id,
                photo=chart_data,
                caption=caption
                # parse_mode removed from send_photo for simplicity
            )
            logger.info(f"Chart sent to user {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Error sending chart: {e}")
            return False

    async def send_error_message(self, chat_id: int, error_type: str) -> bool:
        """Send formatted error message (plain text)."""
        message = self._get_error_message(error_type)
        # Send errors as plain text
        return await self.send_message(chat_id, message, parse_mode=None)

    # Internal formatting methods remain plain text for now
    def _format_portfolio_summary(self, data: Dict) -> str:
        """Format portfolio data into readable plain text message."""
        summary = [f"📊 Portfolio: {data.get('name', 'N/A')}"]
        summary.append(f"\n💰 Total Value: ${data.get('total_value', 0.0):,.2f}")

        for chain, chain_data in data.get('chains', {}).items():
            summary.append(f"\n\n🔗 {chain}: ${chain_data.get('total', 0.0):,.2f}")
            for token, token_data in chain_data.get('tokens', {}).items():
                summary.append(
                    f"  • {token} ({token_data.get('symbol', '?')}): "
                    f"${token_data.get('balance_usd', 0.0):,.2f} "
                    f"({token_data.get('balance', 0.0):,.4f} tokens)"
                )
        return "\n".join(summary)

    def _format_wallet_summary(self, data: Dict) -> str:
        """Format wallet data into readable plain text message."""
        summary = [f"👛 Wallet Summary"]
        summary.append(f"Address: {data.get('address', 'Unknown')}")
        summary.append(f"\n💰 Total Value: ${data.get('total_value', 0.0):,.2f}")

        for chain, chain_data in data.get('chains', {}).items():
            summary.append(f"\n\n🔗 {chain}: ${chain_data.get('total', 0.0):,.2f}")
            for token, token_data in chain_data.get('tokens', {}).items():
                summary.append(
                    f"  • {token} ({token_data.get('symbol', '?')}): "
                    f"${token_data.get('balance_usd', 0.0):,.2f} "
                    f"({token_data.get('balance', 0.0):,.4f} tokens)"
                )
        return "\n".join(summary)

    def _get_error_message(self, error_type: str) -> str:
        """Get appropriate error message based on error type."""
        error_messages = {
            'invalid_address': '❌ Invalid wallet address provided.',
            'invalid_chain': '❌ Unsupported blockchain.',
            'api_error': '❌ Unable to fetch data. Please try again later.',
            'invalid_alert': '❌ Invalid alert parameters provided.',
            'portfolio_not_found': '❌ Portfolio not found.',
            'wallet_not_found': '❌ Wallet not found.',
            'permission_denied': '❌ You don\'t have permission to perform this action.',
            'premium_required': '🔒 This feature requires a premium subscription.'
        }
        return error_messages.get(error_type, '❌ An error occurred. Please try again.')
