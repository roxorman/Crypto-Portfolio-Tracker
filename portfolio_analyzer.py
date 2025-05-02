from typing import Dict, List, Optional, Any
import logging
from collections import defaultdict
from telegram.helpers import escape_markdown # Import escape_markdown

logger = logging.getLogger(__name__)

class PortfolioAnalyzer:
    """
    Analyzes pre-filtered portfolio data fetched from APIs (like Mobula)
    and formats it for presentation using MarkdownV2. Assumes input assets meet a minimum
    total value threshold.
    """
    def __init__(self, min_token_value: float = 1.0, top_n_tokens: int = 10):
        """
        Args:
            min_token_value: Minimum USD value for an *individual* token holding
                             on a specific chain/wallet to be included in aggregation
                             (to filter out spam/dust within significant assets).
            top_n_tokens: The number of top tokens to display in the summary.
        """
        self.min_token_value = min_token_value
        self.top_n_tokens = top_n_tokens
        self.logger = logging.getLogger(__name__)

    def _md_escape(self, text: str) -> str:
        """Helper to escape text for MarkdownV2."""
        # Ensure input is string before escaping
        return escape_markdown(str(text), version=2)

    async def analyze_and_format_holdings(self, portfolio_name: str, fetched_data_packages: List[Dict[str, Any]]) -> str:
        """
        Processes structured data packages from PortfolioFetcher, aggregates data,
        filters low-value individual balances, and formats a MarkdownV2 summary message.

        Args:
            portfolio_name: The name of the portfolio being analyzed.
            fetched_data_packages: A list of dictionaries returned by
                                   PortfolioFetcher.fetch_mobula_portfolio_data.
                                   Each dict contains metadata and a pre-filtered 'assets' list.

        Returns:
            A MarkdownV2 formatted string message summarizing the portfolio holdings.
        """
        if not fetched_data_packages:
            self.logger.warning("analyze_and_format_holdings called with no fetched data packages.")
            safe_portfolio_name = self._md_escape(portfolio_name)
            # MarkdownV2 output with manual escapes for static chars
            return f"Portfolio '*{safe_portfolio_name}*' has no holdings data to analyze \\(fetcher returned empty list\\)\\."

        # --- Process and Aggregate Results (logic remains the same) ---
        aggregated_data: Dict[str, Any] = {
            'total_usd_value': 0.0,
            'assets_by_chain': defaultdict(lambda: {'total_usd': 0.0, 'tokens': defaultdict(lambda: {'name': '', 'balance': 0.0, 'balance_usd': 0.0, 'price': 0.0, 'contracts': []})}),
            'all_tokens': defaultdict(lambda: {'name': '', 'total_balance': 0.0, 'total_usd': 0.0, 'price': 0.0}),
            'wallets_summary': defaultdict(lambda: {'total_usd': 0.0, 'chains': defaultdict(lambda: {'total_usd': 0.0, 'tokens': defaultdict(lambda: {'name': '', 'balance': 0.0, 'balance_usd': 0.0, 'price': 0.0, 'contracts': []})})})
        }
        processed_asset_chain_wallet_keys = set()
        total_original_assets = 0
        total_filtered_assets_from_fetcher = 0
        fetcher_threshold = 1.0

        for data_package in fetched_data_packages:
            if not isinstance(data_package, dict) or 'assets' not in data_package or not isinstance(data_package['assets'], list):
                self.logger.warning(f"Skipping invalid data package structure: {data_package}")
                continue

            assets = data_package['assets']
            total_original_assets += data_package.get('original_asset_count', 0)
            total_filtered_assets_from_fetcher += data_package.get('filtered_asset_count', len(assets))
            fetcher_threshold = data_package.get('min_value_threshold', fetcher_threshold)

            if not assets:
                self.logger.info(f"Data package for portfolio '{portfolio_name}' contained no assets after fetcher filtering.")
                continue

            for asset in assets:
                if not isinstance(asset, dict) or 'asset' not in asset or 'price' not in asset or 'cross_chain_balances' not in asset:
                    self.logger.warning(f"Skipping asset with unexpected structure: {asset.get('asset', {}).get('symbol', 'N/A')}")
                    continue

                asset_details = asset.get('asset', {})
                token_symbol = asset_details.get('symbol')
                token_name = asset_details.get('name')
                token_mobula_id = asset_details.get('id')

                if not token_symbol or not token_name:
                    self.logger.warning(f"Skipping asset with missing symbol or name.")
                    continue

                price = float(asset.get('price', 0.0))

                if not isinstance(asset.get('cross_chain_balances'), dict):
                     self.logger.warning(f"Skipping asset '{token_symbol}' due to invalid cross_chain_balances.")
                     continue

                for chain_name, balance_info in asset['cross_chain_balances'].items():
                    if not isinstance(balance_info, dict):
                        self.logger.warning(f"Skipping balance for '{token_symbol}' on chain '{chain_name}' because balance_info is not a dict. Received: {balance_info}")
                        continue
                    if 'balance' not in balance_info:
                        self.logger.warning(f"Skipping balance for '{token_symbol}' on chain '{chain_name}' due to missing 'balance' key. Received: {balance_info}")
                        continue

                    balance = float(balance_info.get('balance', 0.0))
                    wallet_address = balance_info.get('wallet_address', 'unknown')

                    if balance <= 0:
                        self.logger.debug(f"Skipping zero/negative balance for '{token_symbol}' on chain '{chain_name}'.")
                        continue
                    if wallet_address == 'unknown':
                         self.logger.debug(f"Processing balance for '{token_symbol}' on chain '{chain_name}' without wallet_address. Received: {balance_info}")

                    balance_usd = balance * price

                    if balance_usd < self.min_token_value:
                        continue

                    asset_chain_wallet_key = f"{token_mobula_id or token_symbol}-{chain_name}-{wallet_address}"
                    if asset_chain_wallet_key in processed_asset_chain_wallet_keys:
                        self.logger.debug(f"Skipping potentially duplicate balance entry due to missing wallet_address: {asset_chain_wallet_key}")
                        continue
                    processed_asset_chain_wallet_keys.add(asset_chain_wallet_key)

                    chain_agg = aggregated_data['assets_by_chain'][chain_name]
                    chain_agg['total_usd'] += balance_usd
                    chain_token_agg = chain_agg['tokens'][token_symbol]
                    chain_token_agg['name'] = token_name
                    chain_token_agg['balance'] += balance
                    chain_token_agg['balance_usd'] += balance_usd
                    chain_token_agg['price'] = price
                    contract_address = balance_info.get('address')
                    if contract_address and contract_address not in chain_token_agg['contracts']:
                         chain_token_agg['contracts'].append(contract_address)

                    overall_token_agg = aggregated_data['all_tokens'][token_symbol]
                    overall_token_agg['name'] = token_name
                    overall_token_agg['total_balance'] += balance
                    overall_token_agg['total_usd'] += balance_usd
                    overall_token_agg['price'] = price

                    if wallet_address != 'unknown':
                        wallet_agg = aggregated_data['wallets_summary'][wallet_address]
                        wallet_agg['total_usd'] += balance_usd
                        wallet_chain_agg = wallet_agg['chains'][chain_name]
                        wallet_chain_agg['total_usd'] += balance_usd
                        wallet_chain_token_agg = wallet_chain_agg['tokens'][token_symbol]
                        wallet_chain_token_agg['name'] = token_name
                        wallet_chain_token_agg['balance'] += balance
                        wallet_chain_token_agg['balance_usd'] += balance_usd
                        wallet_chain_token_agg['price'] = price
                        if contract_address and contract_address not in wallet_chain_token_agg['contracts']:
                             wallet_chain_token_agg['contracts'].append(contract_address)

        # --- Post-Aggregation Processing (logic remains the same) ---
        aggregated_data['total_usd_value'] = sum(
            token_data['balance_usd']
            for chain_data in aggregated_data['assets_by_chain'].values()
            for token_data in chain_data['tokens'].values()
        )

        significant_tokens_final = {
            symbol: data for symbol, data in aggregated_data['all_tokens'].items()
            if data['total_usd'] >= self.min_token_value
        }
        aggregated_data['all_tokens'] = dict(sorted(significant_tokens_final.items(), key=lambda item: item[1]['total_usd'], reverse=True))

        filtered_assets_by_chain = {}
        for chain, chain_data in aggregated_data['assets_by_chain'].items():
            filtered_tokens = {s: d for s, d in chain_data['tokens'].items() if s in significant_tokens_final}
            if filtered_tokens:
                filtered_assets_by_chain[chain] = {
                    'total_usd': sum(t['balance_usd'] for t in filtered_tokens.values()),
                    'tokens': dict(sorted(filtered_tokens.items(), key=lambda item: item[1]['balance_usd'], reverse=True))
                }
        aggregated_data['assets_by_chain'] = dict(sorted(filtered_assets_by_chain.items(), key=lambda item: item[1]['total_usd'], reverse=True))

        filtered_wallets_summary = {}
        for wallet_address, wallet_data in aggregated_data['wallets_summary'].items():
             if wallet_address == 'unknown': continue
             filtered_chains = {}
             for chain, chain_data in wallet_data['chains'].items():
                 filtered_tokens = {s: d for s, d in chain_data['tokens'].items() if s in significant_tokens_final}
                 if filtered_tokens:
                     filtered_chains[chain] = {
                         'total_usd': sum(t['balance_usd'] for t in filtered_tokens.values()),
                         'tokens': dict(sorted(filtered_tokens.items(), key=lambda item: item[1]['balance_usd'], reverse=True))
                     }
             if filtered_chains:
                 filtered_wallets_summary[wallet_address] = {
                     'total_usd': sum(c['total_usd'] for c in filtered_chains.values()),
                     'chains': filtered_chains
                 }
        aggregated_data['wallets_summary'] = dict(sorted(filtered_wallets_summary.items(), key=lambda item: item[1]['total_usd'], reverse=True))

        # --- Format the message using MarkdownV2 (Stricter Escaping) ---
        safe_portfolio_name = self._md_escape(portfolio_name)

        # Escape formatted numbers AND static symbols explicitly
        min_token_value_str = self._md_escape(f"{self.min_token_value:,.2f}")
        fetcher_threshold_str = self._md_escape(f"{fetcher_threshold:,.2f}")

        if aggregated_data['total_usd_value'] < self.min_token_value:
             # Manually escape static chars: ' * ( ) $ . >=
             return (f"Portfolio \\'*'{safe_portfolio_name}\\*' has no significant holdings "
                     f"\\(\\$'{min_token_value_str}' per balance\\)\\.\n"
                     f"_\\(Fetcher initially found {total_original_assets} assets, "
                     f"filtered to {total_filtered_assets_from_fetcher} assets \\>\\= \\$'{fetcher_threshold_str}' total value\\)_")

        total_value_str = self._md_escape(f"{aggregated_data['total_usd_value']:,.2f}")
        message = [f"📊 *Holdings for Portfolio: {safe_portfolio_name}*"]
        message.append(f"💰 *Total Value:* \\${total_value_str}") # Escape $
        # Escape static chars: _ ( >= $ < ) _
        message.append(f"_\\(Showing assets with \\>\\= \\${fetcher_threshold_str} total value; individual balances \\< \\${min_token_value_str} excluded\\)_")
        message.append("")

        message.append("*Holdings by Chain:*")
        if not aggregated_data['assets_by_chain']:
             message.append("  _\\(No significant assets found on any chain after filtering\\)_") # Escape _ ( ) _
        else:
            for chain, chain_data in aggregated_data['assets_by_chain'].items():
                 safe_chain_name = self._md_escape(chain)
                 chain_total_str = self._md_escape(f"{chain_data['total_usd']:,.2f}")
                 # Escape static chars: ` $
                 message.append(f"  🔗 `{safe_chain_name}`: \\${chain_total_str}")
            message.append("")

        # Escape static chars: * ( > $ ) : *
        message.append(f"*Top {self.top_n_tokens} Tokens \\(\\>\\${min_token_value_str} USD aggregated value\\):*")
        if not aggregated_data['all_tokens']:
             message.append("  _\\(No significant token holdings found after filtering\\)_") # Escape _ ( ) _
        else:
            displayed_tokens = 0
            for symbol, token_data in aggregated_data['all_tokens'].items():
                if displayed_tokens >= self.top_n_tokens:
                    message.append("  \\.\\.\\.") # Escape ...
                    break

                safe_symbol = self._md_escape(symbol)
                safe_name = self._md_escape(token_data['name']) # Handles internal parens
                token_total_usd_str = self._md_escape(f"{token_data['total_usd']:,.2f}")
                balance_str = self._md_escape(f"{token_data['total_balance']:,.4f}")
                price_str = self._md_escape(f"{token_data['price']:,.4f}")

                # Escape static chars: ` ( ) : $ \n ( ` @ $ )
                # Note: safe_name is already escaped, including any internal parentheses.
                message.append(
                    f"  🪙 `{safe_symbol}` \\({safe_name}\\): \\${token_total_usd_str}\n"
                    f"      \\(`{balance_str}` \\@ \\${price_str}\\)"
                )
                displayed_tokens += 1

        full_message = "\n".join(message)
        if len(full_message) > 4096:
             # Escape static chars: \n ( . . . )
             return full_message[:4090] + "\n\\(\\.\\.\\.\\)"

        return full_message
