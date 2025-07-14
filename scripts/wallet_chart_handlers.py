import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown
import io
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from db_manager import DatabaseManager
from api_fetcher import PortfolioFetcher
from notifier import Notifier
from config import Config
from utils import format_address
from core_handlers import CALLBACK_MAIN_MENU_VIEW_CHART, CALLBACK_VIEW_HOLDINGS_BACK_MAIN
from decorators import api_rate_limit

logger = logging.getLogger(__name__)

# Callback data prefixes
CALLBACK_WALLET_CHART_SELECT_PREFIX = "wc_select:"
CALLBACK_WALLET_CHART_PERIOD_PREFIX = "wc_period:"
CALLBACK_WALLET_CHART_MENU_BACK_MAIN = "wc_back_main"

class WalletChartHandlers:
    def __init__(self, db_manager: DatabaseManager, portfolio_fetcher: PortfolioFetcher, notifier: Notifier, config: Config):
        self.db = db_manager
        self.fetcher = portfolio_fetcher
        self.notifier = notifier
        self.config = config
        logger.info("WalletChartHandlers initialized.")
    
    async def show_wallet_chart_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Displays a list of wallets for the user to select for charting."""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        wallets = await self.db.get_user_wallets(user_id)
        if not wallets:
            await query.edit_message_text(
                text="You have no wallets to chart\\. Please add a wallet first\\.",
                parse_mode='MarkdownV2',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data=CALLBACK_VIEW_HOLDINGS_BACK_MAIN)]])
            )
            return
        
        keyboard = []
        for wallet in wallets:
            button_text = f"👛 {wallet.label or format_address(wallet.address)}"
            # The callback data now contains the prefix and the wallet's database ID
            callback_data = f"{CALLBACK_WALLET_CHART_SELECT_PREFIX}{wallet.wallet_id}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
        keyboard.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data=CALLBACK_VIEW_HOLDINGS_BACK_MAIN)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            text="Select a wallet to generate its historical value chart:",
            reply_markup=reply_markup
        )

    async def handle_wallet_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles wallet selection and shows period options."""
        query = update.callback_query
        await query.answer()
        
        # Extract the wallet ID from the callback data, e.g., "wc_select:123"
        wallet_id_str = query.data.split(':')[1]

        periods = {"1D": "day", "1W": "week", "1M": "month", "1Y": "year", "MAX": "max"}
        
        keyboard_rows = []
        row = []
        for display, period_val in periods.items():
            # IMPORTANT: The callback for the period button now INCLUDES the wallet_id_str
            # Format: "wc_period:123:day"
            callback_data = f"{CALLBACK_WALLET_CHART_PERIOD_PREFIX}{wallet_id_str}:{period_val}"
            row.append(InlineKeyboardButton(display, callback_data=callback_data))
            if len(row) == 3:
                keyboard_rows.append(row)
                row = []
        if row:
            keyboard_rows.append(row)
            
        # The back button now simply triggers the initial menu function again
        keyboard_rows.append([InlineKeyboardButton("⬅️ Back to Wallets", callback_data=CALLBACK_MAIN_MENU_VIEW_CHART)])

        await query.edit_message_text(
            text="Select a time period for the chart:",
            reply_markup=InlineKeyboardMarkup(keyboard_rows)
        )

    @api_rate_limit
    async def handle_period_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles period selection, fetches data, and generates the chart."""
        query = update.callback_query
        await query.answer()

        try:
            # CORRECT: Extract wallet_id and period from the callback data
            # e.g., "wc_period:123:week"
            _, wallet_id_str, period = query.data.split(':')
            wallet_id = int(wallet_id_str)
        except (ValueError, IndexError):
            await query.edit_message_text("Invalid selection. Please try again.")
            return

        wallet = await self.db.get_wallet_by_id(wallet_id)
        if not wallet or wallet.user_id != query.from_user.id:
            await query.edit_message_text("Wallet not found or permission denied.")
            return

        wallet_label = wallet.label or format_address(wallet.address)
        # Send a new loading message instead of editing the menu
        loading_message = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"⏳ Generating *{period.upper()}* chart for `{escape_markdown(wallet_label, version=2)}`\\.\\.\\.",
            parse_mode='MarkdownV2'
        )
        
        try:
            chart_data = await self.fetcher.zerion_wallet_chart_data(
                evm_address=wallet.address,
                chart_period=period
            )

            if not chart_data or 'data' not in chart_data or not chart_data['data'].get('attributes', {}).get('points'):
                await loading_message.edit_text(
                    f"❌ No chart data found for wallet '{escape_markdown(wallet_label, version=2)}' for this period\\.",
                    parse_mode='MarkdownV2'
                )
                return
            
            # Generate and send the chart image
            chart_image_buffer = await self.plot_chart(chart_data, wallet_label, period)
            
            # Delete the loading message
            await loading_message.delete()
            
            # Send the chart as a new photo message
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=chart_image_buffer,
                caption=f"📊 Chart for *{escape_markdown(wallet_label, version=2)}* \\({escape_markdown(period.upper(), version=2)}\\)",
                parse_mode='MarkdownV2'
            )
            
        except Exception as e:
            logger.exception(f"Error handling period selection for wallet {wallet_id}: {e}")
            await loading_message.edit_text("❌ An error occurred while generating the chart. Please try again.")

    async def plot_chart(self, chart_data: dict, wallet_label: str, chart_period: str) -> io.BytesIO:
        """Generates a chart from the provided data and returns a BytesIO buffer."""
        points = chart_data['data']['attributes']['points']
        dates = [datetime.fromtimestamp(ts) for ts, val in points]
        values = [val for ts, val in points]

        plt.style.use('default')  # Use default light style
        fig, ax = plt.subplots(figsize=(12, 7))

        # Plot the data
        ax.plot(dates, values, color='tab:blue', linewidth=1.5)

        # Formatting
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x/1000:.1f}K' if x >= 1000 else f'${x:,.0f}'))
        
        plt.setp(ax.get_xticklabels(), rotation=30, ha='right')

        # Title and Labels
        ax.set_title(f'Wallet Value Over Time ({chart_period.capitalize()})', fontsize=16)
        ax.set_ylabel('Value (USD)', fontsize=12)
        ax.set_xlabel('Date', fontsize=12)
        
        ax.grid(True, which='major', linestyle='--', linewidth='0.7', color='lightgrey')
        fig.tight_layout()

        # Annotations
        if values:
            start_val = values[0]
            end_val = values[-1]
            change = end_val - start_val
            percent_change = (change / start_val * 100) if start_val != 0 else 0
            
            # Current value annotation
            ax.annotate(f'Current: ${end_val:,.2f}', 
                        xy=(dates[-1], end_val), 
                        xytext=(8, 0), 
                        textcoords='offset points',
                        bbox=dict(boxstyle="round,pad=0.3", fc="yellow", ec="black", lw=0.5, alpha=0.8),
                        fontsize=10)

            # Change annotation (only if there's a significant change)
            if abs(percent_change) > 0.1:
                # Find a good position for the change annotation (e.g., near the start)
                annotation_date_index = len(dates) // 4
                annotation_date = dates[annotation_date_index]
                annotation_value = values[annotation_date_index]
                
                color = 'red' if change < 0 else 'green'
                ax.annotate(f'{change:+.2f} ({percent_change:+.2f}%)',
                            xy=(annotation_date, annotation_value),
                            xytext=(0, -30),
                            textcoords='offset points',
                            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", lw=0.5),
                            color=color,
                            fontsize=10,
                            ha='center')

        # Save to buffer
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100)
        buf.seek(0)
        plt.close(fig)
        return buf
