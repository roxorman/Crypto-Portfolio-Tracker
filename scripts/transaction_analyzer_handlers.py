import asyncio
import aiohttp
import json
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from db_manager import DatabaseManager
from config import Config
from models import User, Wallet
from telegram.helpers import escape_markdown
from view_handlers import format_transaction_summary

# Callback data prefixes
CALLBACK_ANALYZE_WALLET_PREFIX = "analyze_wallet_"
CALLBACK_ANALYZE_SENT_PREFIX = "analyze_send_"
CALLBACK_ANALYZE_RECEIVED_PREFIX = "analyze_receive_"

from api_fetcher import PortfolioFetcher


class TransactionAnalyzerHandlers:
    def __init__(self, db_manager: DatabaseManager, config: Config, portfolio_fetcher: PortfolioFetcher):
        self.db = db_manager
        self.config = config
        self.portfolio_fetcher = portfolio_fetcher

    def analyze_transactions(self, transactions, operation_type):
        """
        Analyzes a list of transactions and returns a summary.
        """
        if not transactions:
            return "No transactions to analyze."

        summary = {
            "total_transactions": len(transactions),
            "date_range": {
                "start": None,
                "end": None
            },
            "transactions_by_chain": {},
            "total_value_usd": 0,
            "total_fees_usd": 0,
            "additional_insights": {
                "transaction_status_distribution": {},
                "average_transaction_value_usd": 0,
                "transactions_by_day_of_week": {},
                "transactions_by_hour_of_day": {}
            }
        }

        if operation_type == 'send':
            summary['top_recipients_by_value'] = {}
            summary['top_recipients_by_count'] = {}
            summary['top_sent_tokens_usd'] = {}
        else: # receive
            summary['top_senders_by_value'] = {}
            summary['top_senders_by_count'] = {}
            summary['top_received_tokens_usd'] = {}


        dates = []
        total_value_for_avg = 0
        tx_count_for_avg = 0

        for tx in transactions:
            attributes = tx.get('attributes', {})
            
            mined_at_str = attributes.get('mined_at')
            if mined_at_str:
                dt_object = datetime.fromisoformat(mined_at_str.replace('Z', '+00:00'))
                dates.append(dt_object)
                day_of_week = dt_object.strftime('%A')
                hour_of_day = dt_object.hour
                summary['additional_insights']['transactions_by_day_of_week'][day_of_week] = summary['additional_insights']['transactions_by_day_of_week'].get(day_of_week, 0) + 1
                summary['additional_insights']['transactions_by_hour_of_day'][hour_of_day] = summary['additional_insights']['transactions_by_hour_of_day'].get(hour_of_day, 0) + 1

            chain_id = tx.get('relationships', {}).get('chain', {}).get('data', {}).get('id')
            if chain_id:
                summary['transactions_by_chain'][chain_id] = summary['transactions_by_chain'].get(chain_id, 0) + 1

            status = attributes.get('status')
            if status:
                summary['additional_insights']['transaction_status_distribution'][status] = summary['additional_insights']['transaction_status_distribution'].get(status, 0) + 1

            transfers = attributes.get('transfers', [])
            direction = 'out' if operation_type == 'send' else 'in'
            
            for transfer in transfers:
                if transfer.get('direction') == direction:
                    value = transfer.get('value')
                    if isinstance(value, (int, float)):
                        summary['total_value_usd'] += value
                        total_value_for_avg += value
                        tx_count_for_avg += 1
                        
                        actor = transfer.get('recipient') if operation_type == 'send' else transfer.get('sender')
                        if actor:
                            if operation_type == 'send':
                                summary['top_recipients_by_value'][actor] = summary['top_recipients_by_value'].get(actor, 0) + value
                                summary['top_recipients_by_count'][actor] = summary['top_recipients_by_count'].get(actor, 0) + 1
                            else:
                                summary['top_senders_by_value'][actor] = summary['top_senders_by_value'].get(actor, 0) + value
                                summary['top_senders_by_count'][actor] = summary['top_senders_by_count'].get(actor, 0) + 1


                        fungible_info = transfer.get('fungible_info', {})
                        token_symbol = fungible_info.get('symbol')
                        if token_symbol:
                            token_key = 'top_sent_tokens_usd' if operation_type == 'send' else 'top_received_tokens_usd'
                            summary[token_key][token_symbol] = summary[token_key].get(token_symbol, 0) + value

            fee = attributes.get('fee', {})
            fee_value = fee.get('value')
            if isinstance(fee_value, (int, float)):
                summary['total_fees_usd'] += fee_value

        if dates:
            summary['date_range']['start'] = min(dates).isoformat()
            summary['date_range']['end'] = max(dates).isoformat()

        if tx_count_for_avg > 0:
            summary['additional_insights']['average_transaction_value_usd'] = total_value_for_avg / tx_count_for_avg

        if operation_type == 'send':
            summary['top_recipients_by_value'] = {k: v for k, v in sorted(summary['top_recipients_by_value'].items(), key=lambda item: item[1], reverse=True)[:5]}
            summary['top_recipients_by_count'] = {k: v for k, v in sorted(summary['top_recipients_by_count'].items(), key=lambda item: item[1], reverse=True)[:5]}
            summary['top_sent_tokens_usd'] = {k: v for k, v in sorted(summary['top_sent_tokens_usd'].items(), key=lambda item: item[1], reverse=True)[:5]}
        else:
            summary['top_senders_by_value'] = {k: v for k, v in sorted(summary['top_senders_by_value'].items(), key=lambda item: item[1], reverse=True)[:5]}
            summary['top_senders_by_count'] = {k: v for k, v in sorted(summary['top_senders_by_count'].items(), key=lambda item: item[1], reverse=True)[:5]}
            summary['top_received_tokens_usd'] = {k: v for k, v in sorted(summary['top_received_tokens_usd'].items(), key=lambda item: item[1], reverse=True)[:5]}

        summary['additional_insights']['transactions_by_hour_of_day'] = dict(sorted(summary['additional_insights']['transactions_by_hour_of_day'].items()))

        return summary

    async def transaction_analyzer_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id

        user, _ = await self.db.create_user(user_id)
        if not user.is_premium:
            await query.edit_message_text("This feature is for premium users only.")
            return

        wallets = await self.db.get_user_wallets(user_id)
        if not wallets:
            await query.edit_message_text("You have no wallets to analyze. Please add a wallet first.")
            return

        keyboard = []
        for wallet in wallets:
            keyboard.append([InlineKeyboardButton(wallet.label or wallet.address, callback_data=f"{CALLBACK_ANALYZE_WALLET_PREFIX}{wallet.wallet_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Please select a wallet to analyze:", reply_markup=reply_markup)

    async def select_transaction_type_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        wallet_id = int(query.data.split('_')[2])

        keyboard = [
            [InlineKeyboardButton("Sent Transactions", callback_data=f"{CALLBACK_ANALYZE_SENT_PREFIX}{wallet_id}")],
            [InlineKeyboardButton("Received Transactions", callback_data=f"{CALLBACK_ANALYZE_RECEIVED_PREFIX}{wallet_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Please select the transaction type to analyze:", reply_markup=reply_markup)

    async def analyze_wallet_transactions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        parts = query.data.split('_')
        operation_type = parts[1]
        wallet_id = int(parts[2])
        
        wallet = await self.db.get_wallet_by_id(wallet_id)

        if not wallet:
            await query.edit_message_text("Wallet not found.")
            return

        await query.edit_message_text(f"Fetching {operation_type} transactions for {wallet.label or wallet.address}... This may take a moment.")

        transactions = await self.portfolio_fetcher.get_wallet_transactions(wallet.address, operation_type)

        if transactions:
            summary = self.analyze_transactions(transactions, operation_type)
            message = format_transaction_summary(summary, operation_type, wallet.label or wallet.address)
            
            # Split message if too long
            from utils import split_message
            message_chunks = split_message(message)
            
            for i, chunk in enumerate(message_chunks):
                if i == 0:
                    await query.edit_message_text(chunk, parse_mode='MarkdownV2')
                else:
                    await context.bot.send_message(chat_id=query.message.chat_id, text=chunk, parse_mode='MarkdownV2')
        else:
            await query.edit_message_text(f"Could not retrieve or analyze {operation_type} transactions for {wallet.label or wallet.address}.")
