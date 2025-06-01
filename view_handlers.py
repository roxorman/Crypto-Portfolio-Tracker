# view_handlers.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup # Added
from telegram.ext import ContextTypes
from db_manager import DatabaseManager
from api_fetcher import PortfolioFetcher
from notifier import Notifier
from portfolio_analyzer import PortfolioAnalyzer
from utils import format_address, parse_view_args
from telegram.helpers import escape_markdown
import logging
from typing import List, Dict, Optional, Tuple, Any

# Import constants from core_handlers for callback data
from core_handlers import CALLBACK_VIEW_HOLDINGS_BACK_MAIN, CALLBACK_VIEW_HOLDINGS_SELECT_PREFIX # Added

logger = logging.getLogger(__name__)

class ViewHandlers:
    def __init__(self, db_manager: DatabaseManager, portfolio_fetcher: PortfolioFetcher,
                 portfolio_analyzer: PortfolioAnalyzer, notifier: Notifier):
        self.db = db_manager
        self.portfolio_fetcher = portfolio_fetcher
        self.portfolio_analyzer = portfolio_analyzer
        self.notifier = notifier
        logger.info("ViewHandlers initialized.")

    def _create_wallet_specific_asset_entry(self, shared_asset_data: Dict, balance_info: Dict, wallet_address: str) -> Dict:
        price = shared_asset_data.get('price', 0.0)
        token_balance_for_wallet = balance_info.get('balance', 0.0)
        estimated_balance_for_wallet = token_balance_for_wallet * price
        chain_id_full = balance_info.get("chainId", "unknown:unknown")
        chain_id_parts = chain_id_full.split(":")
        chain_key_for_ccb = chain_id_parts[0].capitalize() if chain_id_parts[0] != "unknown" else "UnknownChain"
        chain_id_for_ccb_value = chain_id_parts[0] if chain_id_parts[0] != "unknown" else "unknown"

        return {
            "asset": shared_asset_data.get("asset"),
            "price": price,
            "price_change_24h": shared_asset_data.get("price_change_24h"),
            "estimated_balance": estimated_balance_for_wallet,
            "token_balance": token_balance_for_wallet,
            "allocation": None,
            "contracts_balances": [balance_info],
            "cross_chain_balances": {
                chain_key_for_ccb: {
                    "balance": token_balance_for_wallet,
                    "balanceRaw": balance_info.get("balanceRaw"),
                    "chainId": chain_id_for_ccb_value,
                    "address": balance_info.get("address"),
                    "wallet_address": wallet_address # Added for clarity in the new structure
                }
            },
            "wallets": [wallet_address]
        }

    def _split_batched_api_response(self, batched_api_response_package: Dict[str, Any], original_queried_wallets: List[str]) -> List[Dict[str, Any]]:
        assets_from_batch = batched_api_response_package.get('assets', [])
        min_value_threshold = batched_api_response_package.get('min_value_threshold', 1.0)
        chains_queried_in_batch = batched_api_response_package.get('chains_queried')

        if not assets_from_batch:
            logger.info(f"No assets found in batched API response for wallets: {original_queried_wallets}")
            empty_packages = []
            for addr in original_queried_wallets:
                empty_packages.append({
                    "wallets_queried": [addr],
                    "chains_queried": chains_queried_in_batch,
                    "api_reported_total_balance": 0.0,
                    "original_asset_count": 0,
                    "filtered_asset_count": 0,
                    "min_value_threshold": min_value_threshold,
                    "assets": []
                })
            return empty_packages

        per_wallet_data_packages = {
            addr: {
                "wallets_queried": [addr],
                "chains_queried": chains_queried_in_batch,
                "api_reported_total_balance": 0.0,
                "original_asset_count": 0,
                "filtered_asset_count": 0,
                "min_value_threshold": min_value_threshold,
                "assets": []
            } for addr in original_queried_wallets
        }

        for asset_data in assets_from_batch:
            asset_holding_wallets = asset_data.get('wallets', [])
            contracts_balances = asset_data.get('contracts_balances', [])

            if not asset_holding_wallets or not contracts_balances or len(asset_holding_wallets) != len(contracts_balances):
                logger.warning(f"Skipping asset due to inconsistent wallet/balance data: {asset_data.get('asset', {}).get('symbol')}")
                continue

            for i, wallet_address_holding_asset in enumerate(asset_holding_wallets):
                if wallet_address_holding_asset in per_wallet_data_packages:
                    balance_info_for_this_wallet = contracts_balances[i]
                    balance_info_for_this_wallet['wallet_address'] = wallet_address_holding_asset 

                    wallet_specific_asset_entry = self._create_wallet_specific_asset_entry(
                        asset_data, balance_info_for_this_wallet, wallet_address_holding_asset
                    )

                    per_wallet_data_packages[wallet_address_holding_asset]['original_asset_count'] += 1
                    if wallet_specific_asset_entry.get('estimated_balance', 0.0) >= min_value_threshold:
                        per_wallet_data_packages[wallet_address_holding_asset]['assets'].append(wallet_specific_asset_entry)
                        per_wallet_data_packages[wallet_address_holding_asset]['filtered_asset_count'] += 1

        for addr in per_wallet_data_packages:
            total_bal = sum(asset.get('estimated_balance', 0.0) for asset in per_wallet_data_packages[addr]['assets'])
            per_wallet_data_packages[addr]['api_reported_total_balance'] = total_bal
            if not per_wallet_data_packages[addr]['assets']:
                 logger.info(f"Wallet {addr} had assets in batch but none met value threshold ${min_value_threshold:.2f}.")

        final_packages = [
            pkg for pkg in per_wallet_data_packages.values() if pkg['original_asset_count'] > 0 or pkg['assets']
        ]
        if not final_packages and original_queried_wallets:
            logger.info(f"No assets found for any of the queried wallets in the batch: {original_queried_wallets}")
            return [per_wallet_data_packages[addr] for addr in original_queried_wallets if addr in per_wallet_data_packages]

        return final_packages

    async def _fetch_portfolio_data(self, source_name: str, associations: List[Any], single_wallet_chain_filter: Optional[str] = None) -> Optional[List[Dict]]:
        if not associations:
            logger.warning(f"No associations provided for source '{source_name}' to fetch data.")
            return []

        wallet_addresses_to_fetch = []
        chain_param_for_api = single_wallet_chain_filter

        is_single_wallet_direct_call = False
        if associations and isinstance(associations[0], dict) and 'wallet' in associations[0]:
            is_single_wallet_direct_call = True
            wallet_obj = associations[0]['wallet']
            wallet_addresses_to_fetch.append(wallet_obj.address)
            logger.info(f"Preparing single wallet fetch for {wallet_obj.address} on chain: {chain_param_for_api or 'All'}")
        else: 
            for assoc in associations:
                if hasattr(assoc, 'wallet') and assoc.wallet and assoc.wallet.address:
                    if assoc.wallet.address not in wallet_addresses_to_fetch:
                        wallet_addresses_to_fetch.append(assoc.wallet.address)
            if not wallet_addresses_to_fetch:
                logger.warning(f"No valid wallet addresses found in portfolio '{source_name}'.")
                return []
            chain_param_for_api = None 
            logger.info(f"Preparing batched portfolio fetch for {len(wallet_addresses_to_fetch)} wallets in '{source_name}'. Chains: All")

        if not wallet_addresses_to_fetch:
             logger.error(f"Logic error: No wallet addresses collected for fetching for source '{source_name}'.")
             return None

        api_response_package = await self.portfolio_fetcher.fetch_mobula_portfolio_data(
            wallets=wallet_addresses_to_fetch,
            chains=[chain_param_for_api] if chain_param_for_api else None
        )

        if api_response_package is None:
            logger.error(f"API call failed for source '{source_name}', wallets: {wallet_addresses_to_fetch}")
            return None

        if not api_response_package.get('assets'):
            logger.info(f"API call for source '{source_name}' (Wallets: {wallet_addresses_to_fetch}, Chains: {chain_param_for_api or 'All'}) returned no assets.")
            empty_packages = []
            for addr in wallet_addresses_to_fetch:
                empty_packages.append({
                    "wallets_queried": [addr],
                    "chains_queried": api_response_package.get('chains_queried', [chain_param_for_api] if chain_param_for_api else None),
                    "api_reported_total_balance": 0.0,
                    "original_asset_count": 0,
                    "filtered_asset_count": 0,
                    "min_value_threshold": api_response_package.get('min_value_threshold', 1.0),
                    "assets": []
                })
            return empty_packages

        if is_single_wallet_direct_call and len(wallet_addresses_to_fetch) == 1:
            logger.info(f"Received data for single wallet direct call: {wallet_addresses_to_fetch[0]}")
            return [api_response_package]

        logger.info(f"Splitting batched API response for source '{source_name}'")
        processed_api_results = self._split_batched_api_response(api_response_package, wallet_addresses_to_fetch)

        if not processed_api_results:
            logger.warning(f"Splitting batched response for '{source_name}' yielded no per-wallet packages with assets.")
            empty_packages = [] 
            for addr in wallet_addresses_to_fetch:
                 empty_packages.append({
                    "wallets_queried": [addr],
                    "chains_queried": api_response_package.get('chains_queried', [chain_param_for_api] if chain_param_for_api else None),
                    "api_reported_total_balance": 0.0,
                    "original_asset_count": 0,
                    "filtered_asset_count": 0,
                    "min_value_threshold": api_response_package.get('min_value_threshold', 1.0),
                    "assets": []
                })
            return empty_packages
        return processed_api_results

    async def _analyze_portfolio_data(self, title: str, api_results: List[Dict]) -> Optional[str]:
        if not api_results:
             logger.warning(f"No API results provided for analysis of '{title}'.")
             safe_title = escape_markdown(title, version=2)
             return f"ℹ️ No holdings data found or processed for '{safe_title}'\\.", None
        try:
            formatted_message, processed_data = await self.portfolio_analyzer.analyze_and_format_holdings(title, api_results)
            return formatted_message, processed_data
        except Exception as e:
            logger.exception(f"Error during data analysis for '{title}': {e}")
            return None, None

    async def view_holdings(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        chat_id = None

        if update.message:
            chat_id = update.message.chat_id
        elif update.callback_query:
            chat_id = update.callback_query.message.chat_id
            # If called from callback, edit the message that had the selection buttons
            # to show "Fetching..." or remove the keyboard.
            # For now, let's assume the "Fetching..." message will be a new one.
            # await update.callback_query.edit_message_text("Fetching data...") # Example
        else:
            logger.error("view_holdings: Could not determine chat_id from update.")
            return

        args = context.args
        if not args or len(args) == 0:
            usage_text = (
                "Usage: /view \\<Address \\| Label \\| PortfolioName\\> [chain:\\<ChainName\\>]\n"
                "Example: `/view 0x123...abc`\n"
                "Example: `/view MyPortfolio`\n"
                "Example: `/view 0xabc...def chain:base`"
            )
            if update.message:
                 await context.bot.send_message(chat_id=chat_id, text=usage_text, parse_mode='MarkdownV2')
            else:
                 logger.error(f"view_holdings called from callback for chat {chat_id} without context.args set.")
                 await context.bot.send_message(chat_id=chat_id, text="Internal error: Missing identifier for viewing holdings.")
            return
            
        identifier, chain_filter = parse_view_args(args) 

        safe_id = escape_markdown(identifier, version=2)
        safe_chain_filter_msg = escape_markdown(chain_filter, version=2) if chain_filter else "All Chains"
        
        await context.bot.send_message(chat_id=chat_id, text=f"⏳ Fetching holdings for `{safe_id}` \\({safe_chain_filter_msg}\\)\\.\\.\\.", parse_mode='MarkdownV2')

        api_results = None
        analysis_title = identifier

        target_portfolio = await self.db.get_portfolio_by_name(user_id, identifier)

        if target_portfolio:
            analysis_title = target_portfolio.name
            logger.info(f"User {user_id} viewing portfolio: {target_portfolio.name}, ID: {target_portfolio.portfolio_id}")
            db_associations = await self.db.get_portfolio_wallet_associations(target_portfolio.portfolio_id)
            if not db_associations:
                await context.bot.send_message(chat_id=chat_id, text=f"ℹ️ Portfolio '{safe_id}' has no wallets added yet\\. Use `/padd`\\.", parse_mode='MarkdownV2')
                return
            api_results = await self._fetch_portfolio_data(target_portfolio.name, db_associations, None)
        else:
            target_wallet = await self.db.find_user_wallet(user_id, identifier)
            if target_wallet:
                analysis_title = target_wallet.label or format_address(target_wallet.address)
                logger.info(f"User {user_id} viewing single wallet: {target_wallet.address} (Label: {target_wallet.label}), Chain filter: {chain_filter}")
                api_results = await self._fetch_portfolio_data(
                    f"Wallet_{format_address(target_wallet.address)}",
                    [{'wallet': target_wallet, 'chain_for_api': chain_filter}],
                    chain_filter
                )
            else:
                await context.bot.send_message(chat_id=chat_id, text=f"❌ Identifier '{safe_id}' not found\\. It's not a tracked wallet (address/label) or an existing portfolio name\\.", parse_mode='MarkdownV2')
                return

        if api_results is None:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Failed to fetch holdings data for '{safe_id}'\\. Check logs or try again later\\.", parse_mode='MarkdownV2')
            return
        if not api_results: 
            await context.bot.send_message(chat_id=chat_id, text=f"ℹ️ No assets found for '{safe_id}' (or specified chain filter '{safe_chain_filter_msg}')\\. It might be empty or all assets were filtered out by the fetcher\\.", parse_mode='MarkdownV2')
            return

        formatted_message, processed_data = await self._analyze_portfolio_data(analysis_title, api_results)
        
        if formatted_message is None and processed_data is None:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ An error occurred while analyzing the data for '{safe_id}'\\. Please check logs\\.", parse_mode='MarkdownV2')
            return

        chart_sent = False 
        
        if formatted_message:
            await self.notifier.send_message(user_id, formatted_message, parse_mode='MarkdownV2')
        elif not formatted_message: 
             await context.bot.send_message(chat_id=chat_id, text=f"ℹ️ No data to display for '{safe_id}' after analysis\\.", parse_mode='MarkdownV2')

    async def show_view_holdings_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id

        portfolios = await self.db.get_user_portfolios(user_id)
        wallets = await self.db.get_user_wallets(user_id)

        keyboard = []
        if not portfolios and not wallets:
            text = "You don't have any portfolios or tracked wallets yet\\. Please add some first\\!"
            keyboard.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data=CALLBACK_VIEW_HOLDINGS_BACK_MAIN)])
        else:
            text = "Select a portfolio or wallet to view its holdings:"
            for p in portfolios:
                button_text = f"💼 {p.name}"
                callback_data = f"{CALLBACK_VIEW_HOLDINGS_SELECT_PREFIX}p_{p.portfolio_id}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
            
            for w in wallets:
                button_text = f"👛 {w.label or format_address(w.address)}"
                callback_data = f"{CALLBACK_VIEW_HOLDINGS_SELECT_PREFIX}w_{w.wallet_id}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
            
            keyboard.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data=CALLBACK_VIEW_HOLDINGS_BACK_MAIN)])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='MarkdownV2')

    async def handle_view_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        data_parts = query.data.split(':')
        if len(data_parts) < 2 or not data_parts[1]:
            logger.error(f"Invalid callback data for view selection: {query.data}")
            await query.edit_message_text("❌ Invalid selection. Please try again or go back to the main menu.")
            return

        item_type_and_id = data_parts[1] 
        item_type = item_type_and_id[0] 
        item_id = int(item_type_and_id[2:]) 

        identifier_for_view_holdings = None
        if item_type == 'p':
            portfolio = await self.db.get_portfolio_by_id(item_id)
            if portfolio and portfolio.user_id == user_id:
                identifier_for_view_holdings = portfolio.name
            else:
                await query.edit_message_text("❌ Portfolio not found or does not belong to you.")
                return
        elif item_type == 'w':
            wallet = await self.db.get_wallet_by_id(item_id)
            if wallet and wallet.user_id == user_id:
                identifier_for_view_holdings = wallet.address 
            else:
                await query.edit_message_text("❌ Wallet not found or does not belong to you.")
                return
        else:
            await query.edit_message_text("❌ Unknown item type selected.")
            return

        if identifier_for_view_holdings:
            # Edit the current message to remove buttons and show "Fetching..."
            # This provides immediate feedback on the button press.
            await query.edit_message_text(text=f"⏳ Fetching holdings for {escape_markdown(identifier_for_view_holdings, version=2)}\\.\\.\\.", parse_mode='MarkdownV2', reply_markup=None)
            
            context.args = [identifier_for_view_holdings]
            await self.view_holdings(update, context) # view_holdings will send new messages
            context.args = [] 
        else:
            await query.edit_message_text("❌ Could not retrieve item details. Please try again.")

    async def view_pnl_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        args = context.args
        if not args or len(args) == 0:
            # Use context.bot.send_message for consistency if this is ever called from a non-command context
            await context.bot.send_message(
                chat_id=update.effective_chat.id, # Use effective_chat.id for safety
                text=(
                    "Usage: /pnl \\<Address \\| Label \\| PortfolioName\\> [chain:\\<ChainName\\>]\n"
                    "Example: `/pnl 0x123...abc`\n"
                    "Example: `/pnl MyPortfolio`\n"
                    "Example: `/pnl 0xabc...def chain:base`"
                ), 
                parse_mode='MarkdownV2'
            )
            return
        identifier, chain_filter = parse_view_args(args)
