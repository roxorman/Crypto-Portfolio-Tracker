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
        return escape_markdown(str(text), version=2)

    def _initialize_aggregated_data(self) -> Dict[str, Any]:
        """Initializes the main data structure for aggregation."""
        return {
            'total_usd_value': 0.0,
            'assets_by_chain': defaultdict(lambda: {'total_usd': 0.0, 'tokens': defaultdict(lambda: {'name': '', 'balance': 0.0, 'balance_usd': 0.0, 'price': 0.0, 'contracts': []})}),
            'all_tokens': defaultdict(lambda: {'name': '', 'total_balance': 0.0, 'total_usd': 0.0, 'price': 0.0}),
            'wallets_summary': defaultdict(lambda: {'total_usd': 0.0, 'chains': defaultdict(lambda: {'total_usd': 0.0, 'tokens': defaultdict(lambda: {'name': '', 'balance': 0.0, 'balance_usd': 0.0, 'price': 0.0, 'contracts': []})})})
        }

    def _aggregate_raw_asset_data(self, fetched_data_packages: List[Dict[str, Any]]) -> tuple[Dict[str, Any], int, int, float]:
        """
        Aggregates raw asset data from multiple fetcher packages.
        Filters individual balances below self.min_token_value.
        """
        aggregated_data = self._initialize_aggregated_data()
        processed_asset_chain_wallet_keys = set()
        total_original_assets = 0
        total_filtered_assets_from_fetcher = 0
        # Use the threshold from the first package, or default if none
        fetcher_threshold = fetched_data_packages[0].get('min_value_threshold', 1.0) if fetched_data_packages else 1.0


        for data_package in fetched_data_packages:
            if not isinstance(data_package, dict) or 'assets' not in data_package or not isinstance(data_package['assets'], list):
                self.logger.warning(f"Skipping invalid data package structure: {data_package}")
                continue

            assets = data_package['assets']
            total_original_assets += data_package.get('original_asset_count', 0)
            total_filtered_assets_from_fetcher += data_package.get('filtered_asset_count', len(assets))
            # Update fetcher_threshold if a more specific one is found in packages (though usually consistent)
            fetcher_threshold = data_package.get('min_value_threshold', fetcher_threshold)


            if not assets:
                self.logger.info("A data package contained no assets after fetcher filtering.")
                continue

            for asset in assets:
                if not isinstance(asset, dict) or 'asset' not in asset or 'price' not in asset or 'cross_chain_balances' not in asset:
                    self.logger.warning(f"Skipping asset with unexpected structure: {asset.get('asset', {}).get('symbol', 'N/A')}")
                    continue

                asset_details = asset.get('asset', {})
                token_symbol = asset_details.get('symbol')
                token_name = asset_details.get('name')
                # Assuming 'id' from asset_details is the unique identifier like mobula_id or cmc_id
                token_unique_id = asset_details.get('id') 

                if not token_symbol or not token_name:
                    self.logger.warning("Skipping asset with missing symbol or name.")
                    continue

                price = float(asset.get('price', 0.0))

                if not isinstance(asset.get('cross_chain_balances'), dict):
                     self.logger.warning(f"Skipping asset '{token_symbol}' due to invalid cross_chain_balances.")
                     continue

                for chain_name, balance_info in asset['cross_chain_balances'].items():
                    if not isinstance(balance_info, dict) or 'balance' not in balance_info:
                        self.logger.warning(f"Skipping balance for '{token_symbol}' on chain '{chain_name}' due to missing or invalid balance_info.")
                        continue
                    
                    balance = float(balance_info.get('balance', 0.0))
                    wallet_address = balance_info.get('wallet_address', 'unknown') # Mobula specific field

                    if balance <= 0:
                        continue
                    
                    balance_usd = balance * price
                    if balance_usd < self.min_token_value: # Filter out very small individual balances
                        continue

                    # Deduplication key for balances that might appear across multiple wallets in a single asset entry
                    # (e.g. if Mobula returns one asset with balances from multiple queried wallets)
                    asset_chain_wallet_key = f"{token_unique_id or token_symbol}-{chain_name}-{wallet_address}"
                    if asset_chain_wallet_key in processed_asset_chain_wallet_keys and wallet_address != 'unknown':
                        # This check is more relevant if a single API call returns an asset's balance across multiple wallets
                        # and we want to avoid double-counting if not properly distinguished by wallet_address.
                        # For now, if wallet_address is 'unknown', we might sum it up.
                        # If Mobula's `assets` list is per-wallet, this might be less of an issue.
                        # Given the current structure, this key helps if an asset appears multiple times with same chain/wallet.
                        self.logger.debug(f"Skipping potentially duplicate balance entry: {asset_chain_wallet_key}")
                        continue
                    processed_asset_chain_wallet_keys.add(asset_chain_wallet_key)
                    
                    # Aggregate by chain
                    chain_agg = aggregated_data['assets_by_chain'][chain_name]
                    chain_agg['total_usd'] += balance_usd
                    chain_token_agg = chain_agg['tokens'][token_symbol]
                    chain_token_agg['name'] = token_name
                    chain_token_agg['balance'] += balance
                    chain_token_agg['balance_usd'] += balance_usd
                    chain_token_agg['price'] = price # Store last known price
                    contract_address = balance_info.get('address') # Contract address on this chain
                    if contract_address and contract_address not in chain_token_agg['contracts']:
                         chain_token_agg['contracts'].append(contract_address)

                    # Aggregate all tokens globally
                    overall_token_agg = aggregated_data['all_tokens'][token_symbol]
                    overall_token_agg['name'] = token_name
                    overall_token_agg['total_balance'] += balance
                    overall_token_agg['total_usd'] += balance_usd
                    overall_token_agg['price'] = price

                    # Aggregate by specific wallet address if available
                    if wallet_address != 'unknown':
                        wallet_summary = aggregated_data['wallets_summary'][wallet_address]
                        wallet_summary['total_usd'] += balance_usd
                        wallet_chain_summary = wallet_summary['chains'][chain_name]
                        wallet_chain_summary['total_usd'] += balance_usd
                        wallet_token_summary = wallet_chain_summary['tokens'][token_symbol]
                        wallet_token_summary['name'] = token_name
                        wallet_token_summary['balance'] += balance
                        wallet_token_summary['balance_usd'] += balance_usd
                        wallet_token_summary['price'] = price
                        if contract_address and contract_address not in wallet_token_summary['contracts']:
                             wallet_token_summary['contracts'].append(contract_address)
        
        return aggregated_data, total_original_assets, total_filtered_assets_from_fetcher, fetcher_threshold

    def _process_aggregated_data(self, aggregated_data: Dict[str, Any]) -> Dict[str, Any]:
        """Filters and sorts the aggregated data."""
        # Calculate overall total USD value from the already filtered individual balances
        aggregated_data['total_usd_value'] = sum(
            chain_data['total_usd'] for chain_data in aggregated_data['assets_by_chain'].values()
        )

        # Filter and sort all_tokens by total_usd (already filtered by min_token_value at individual balance level)
        # We can apply another threshold here if needed for the *aggregated* value of a token
        significant_tokens_final = {
            symbol: data for symbol, data in aggregated_data['all_tokens'].items()
            # if data['total_usd'] >= self.min_token_value # This was already applied per balance,
            # but could be applied again for total aggregated value of a token if desired.
            # For now, assume all tokens in all_tokens are significant enough from previous step.
        }
        aggregated_data['all_tokens'] = dict(sorted(
            significant_tokens_final.items(), 
            key=lambda item: item[1]['total_usd'], 
            reverse=True
        ))

        # Filter and sort assets_by_chain
        filtered_assets_by_chain = {}
        for chain, chain_data in aggregated_data['assets_by_chain'].items():
            # Tokens within each chain were already filtered by min_token_value for their balance on that chain/wallet
            # Sort tokens within the chain
            sorted_tokens_in_chain = dict(sorted(
                chain_data['tokens'].items(), 
                key=lambda item: item[1]['balance_usd'], 
                reverse=True
            ))
            if sorted_tokens_in_chain: # Only include chain if it has tokens after filtering
                filtered_assets_by_chain[chain] = {
                    'total_usd': chain_data['total_usd'], # This total is already correct
                    'tokens': sorted_tokens_in_chain
                }
        aggregated_data['assets_by_chain'] = dict(sorted(
            filtered_assets_by_chain.items(), 
            key=lambda item: item[1]['total_usd'], 
            reverse=True
        ))
        
        # Filter and sort wallets_summary (similar logic)
        filtered_wallets_summary = {}
        for wallet_address, wallet_data in aggregated_data['wallets_summary'].items():
            if wallet_address == 'unknown': continue # Should not happen if filtered earlier
            
            filtered_chains_in_wallet = {}
            for chain, chain_data_in_wallet in wallet_data['chains'].items():
                sorted_tokens_in_wallet_chain = dict(sorted(
                    chain_data_in_wallet['tokens'].items(),
                    key=lambda item: item[1]['balance_usd'],
                    reverse=True
                ))
                if sorted_tokens_in_wallet_chain:
                    filtered_chains_in_wallet[chain] = {
                        'total_usd': chain_data_in_wallet['total_usd'],
                        'tokens': sorted_tokens_in_wallet_chain
                    }
            
            if filtered_chains_in_wallet:
                # Recalculate wallet total_usd based on its filtered chains
                wallet_total_usd = sum(c_data['total_usd'] for c_data in filtered_chains_in_wallet.values())
                if wallet_total_usd > 0: # Only include wallet if it has value
                    filtered_wallets_summary[wallet_address] = {
                        'total_usd': wallet_total_usd,
                        'chains': dict(sorted(filtered_chains_in_wallet.items(), key=lambda item: item[1]['total_usd'], reverse=True))
                    }
        aggregated_data['wallets_summary'] = dict(sorted(
            filtered_wallets_summary.items(),
            key=lambda item: item[1]['total_usd'],
            reverse=True
        ))
        return aggregated_data

    def _format_summary_message_markdown(
        self, 
        portfolio_name: str, 
        processed_data: Dict[str, Any],
        total_original_assets: int, # From fetcher
        total_filtered_assets_from_fetcher: int, # From fetcher
        fetcher_threshold: float # From fetcher
    ) -> str:
        """Formats the processed data into a MarkdownV2 string."""
        safe_portfolio_name = self._md_escape(portfolio_name)
        min_token_value_str = self._md_escape(f"{self.min_token_value:,.2f}")
        fetcher_threshold_str = self._md_escape(f"{fetcher_threshold:,.2f}")

        # This check is now done in the main function before calling this formatter
        # if processed_data['total_usd_value'] < self.min_token_value:
        #      return (f"Portfolio \\'*'{safe_portfolio_name}\\*' has no significant holdings "
        #              f"\\(\\$'{min_token_value_str}' per balance\\)\\.\n"
        #              f"_\\(Fetcher initially found {total_original_assets} assets, "
        #              f"filtered to {total_filtered_assets_from_fetcher} assets \\>\\= \\$'{fetcher_threshold_str}' total value\\)_")

        total_value_str = self._md_escape(f"{processed_data['total_usd_value']:,.2f}")
        message = [f"📊 *Holdings for Portfolio: {safe_portfolio_name}*"]
        message.append(f"💰 *Total Value:* \\${total_value_str}")
        message.append(f"_\\(Fetcher threshold \\>\\= \\${fetcher_threshold_str} total per asset; individual balances \\< \\${min_token_value_str} excluded\\)_")
        message.append("")

        message.append("*Holdings by Chain:*")
        if not processed_data['assets_by_chain']:
             message.append("  _\\(No significant assets found on any chain after filtering\\)_")
        else:
            for chain, chain_data in processed_data['assets_by_chain'].items():
                 safe_chain_name = self._md_escape(chain)
                 chain_total_str = self._md_escape(f"{chain_data['total_usd']:,.2f}")
                 message.append(f"  🔗 `{safe_chain_name}`: \\${chain_total_str}")
            message.append("")

        message.append(f"*Top {self.top_n_tokens} Tokens \\(Aggregated Value \\>\\= \\${min_token_value_str}\\):*")
        if not processed_data['all_tokens']:
             message.append("  _\\(No significant token holdings found after filtering\\)_")
        else:
            displayed_tokens = 0
            for symbol, token_data in processed_data['all_tokens'].items():
                if displayed_tokens >= self.top_n_tokens:
                    message.append("  \\.\\.\\.")
                    break
                
                # Ensure all parts are strings before escaping
                safe_symbol = self._md_escape(str(symbol))
                safe_name = self._md_escape(str(token_data.get('name', 'N/A')))
                token_total_usd_str = self._md_escape(f"{token_data.get('total_usd', 0.0):,.2f}")
                balance_str = self._md_escape(f"{token_data.get('total_balance', 0.0):,.4f}")
                price_str = self._md_escape(f"{token_data.get('price', 0.0):,.4f}")

                message.append(
                    f"  🪙 `{safe_symbol}` \\({safe_name}\\): *\\${token_total_usd_str}*\n"
                    f"      \\(`{balance_str}` \\@ \\${price_str}\\)"
                )
                displayed_tokens += 1
        
            # Optionally add wallet-specific summary if needed, for now focusing on portfolio summary
            if processed_data['wallets_summary']:
                message.append("\n*Summary by Wallet:*")
                for wallet_addr, wallet_details in processed_data['wallets_summary'].items():
                    safe_addr = self._md_escape(wallet_addr)
                    wallet_total_str = self._md_escape(f"{wallet_details['total_usd']:,.2f}")
                    message.append(f"  💼 `{safe_addr}`: \\${wallet_total_str}")
                    # Could add more details per wallet if desired

        full_message = "\n".join(message)
        if len(full_message) > 4096:
             return full_message[:4090] + "\n\\(\\.\\.\\.\\)"
        return full_message

    async def analyze_and_format_holdings(self, portfolio_name: str, fetched_data_packages: List[Dict[str, Any]]) -> str:
        """
        Processes structured data packages from PortfolioFetcher, aggregates data,
        filters low-value individual balances, and formats a MarkdownV2 summary message.
        """
        if not fetched_data_packages:
            self.logger.warning("analyze_and_format_holdings called with no fetched data packages.")
            safe_portfolio_name = self._md_escape(portfolio_name)
            return f"Portfolio '*{safe_portfolio_name}*' has no holdings data to analyze \\(fetcher returned empty list\\)\\."

        # Step 1: Aggregate raw data
        raw_aggregated_data, total_original, total_filtered_fetcher, fetcher_thresh = self._aggregate_raw_asset_data(fetched_data_packages)

        # Step 2: Process (filter, sort) aggregated data
        processed_data = self._process_aggregated_data(raw_aggregated_data)
        
        # Check for significance before formatting the full message
        # Use fetcher_thresh for the initial "no data" message as it reflects what fetcher considered significant enough to return
        if processed_data['total_usd_value'] < fetcher_thresh and not processed_data['assets_by_chain']: # Check if anything substantial remains
             min_token_value_str = self._md_escape(f"{self.min_token_value:,.2f}") # This is the analyzer's own filter
             fetcher_threshold_str = self._md_escape(f"{fetcher_thresh:,.2f}")
             safe_portfolio_name = self._md_escape(portfolio_name)
             return (f"Portfolio \\'*'{safe_portfolio_name}\\*' has no significant holdings "
                     f"after filtering \\(min balance value \\${min_token_value_str}\\)\\.\n"
                     f"_\\(Fetcher initially found {total_original} assets, "
                     f"filtered to {total_filtered_fetcher} assets \\>\\= \\$'{fetcher_threshold_str}' total value per asset type\\)_")
        
        # Step 3: Format the message
        formatted_message = self._format_summary_message_markdown(
            portfolio_name, 
            processed_data,
            total_original,
            total_filtered_fetcher,
            fetcher_thresh
        )
        
        return formatted_message, processed_data
