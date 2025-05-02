from typing import Dict, List, Optional, Tuple, Any # Added Any
import requests
import asyncio
import logging
from models import Portfolio, Wallet, PortfolioWalletAssociation
from config import Config

class PortfolioFetcher:
    """Handles fetching raw portfolio data using Mobula API and pre-filtering."""

    def __init__(self):
        self.config = Config()
        # Base URL for Mobula API, specifically the wallet endpoint for portfolio data
        self.base_url = "https://api.mobula.io/api/1/wallet"
        self.api_key = self.config.MOBULA_API_KEY
        self.logger = logging.getLogger(__name__)


    async def fetch_mobula_portfolio_data(
        self,
        wallets: List[str],
        chains: Optional[List[str]] = None,
        min_value_threshold: float = 1.0 # Add threshold parameter
    ) -> Optional[Dict[str, Any]]: # Update return type hint
        """
        Fetches portfolio data from Mobula API, filters assets by minimum total value,
        and returns a structured dictionary.

        Args:
            wallets: A list of wallet addresses (strings).
            chains: An optional list of chain names (strings) to filter by.
            min_value_threshold: Minimum total USD value for an asset to be included.

        Returns:
            A dictionary containing metadata and the filtered list of assets,
            or None if the request failed or the response was invalid.
            Structure:
            {
                "wallets_queried": List[str],
                "chains_queried": Optional[List[str]],
                "api_reported_total_balance": Optional[float],
                "original_asset_count": int,
                "filtered_asset_count": int,
                "min_value_threshold": float,
                "assets": List[Dict] # Filtered assets
            }
        """
        if not wallets:
            self.logger.warning("fetch_mobula_portfolio_data called with no wallets.")
            return None

        url = f"{self.base_url}/portfolio"
        request_chains = ",".join(chains) if chains else None
        params = {
            "wallets": ",".join(wallets),
            "chains": request_chains,
            "filterSpam": "true",
            "liqmin": 1000,
            "unlistedAssets": "false",
        }
        params = {k: v for k, v in params.items() if v is not None}

        headers = {"Authorization": self.api_key}
        self.logger.info(f"Fetching Mobula /portfolio: wallets={len(wallets)}, chains={params.get('chains')}")

        try:
            response = requests.get(url, params=params, headers=headers, timeout=20) # Increased timeout slightly
            response.raise_for_status()
            raw_data = response.json()

            # --- Validate and Process Response ---
            if not isinstance(raw_data, dict) or 'data' not in raw_data or not isinstance(raw_data['data'], dict):
                self.logger.error(f"Invalid Mobula response structure (missing top-level 'data' dict): {raw_data}")
                return None

            data_block = raw_data['data']
            original_assets = data_block.get('assets')
            api_reported_total = data_block.get('total_wallet_balance')

            if not isinstance(original_assets, list):
                self.logger.error(f"Invalid Mobula response structure (missing or invalid 'assets' list): {raw_data}")
                # Return structure indicating failure but providing context
                return {
                    "wallets_queried": wallets,
                    "chains_queried": chains,
                    "api_reported_total_balance": api_reported_total,
                    "original_asset_count": 0,
                    "filtered_asset_count": 0,
                    "min_value_threshold": min_value_threshold,
                    "assets": [] # Empty list as assets couldn't be processed
                }

            # --- Filter Assets ---
            filtered_assets = []
            for asset in original_assets:
                try:
                    if not isinstance(asset, dict) or 'price' not in asset or 'cross_chain_balances' not in asset:
                        self.logger.warning(f"Skipping asset with unexpected structure during filtering: {asset.get('asset', {}).get('symbol', 'N/A')}")
                        continue

                    price = float(asset.get('price', 0.0))
                    total_asset_value = 0.0

                    if isinstance(asset['cross_chain_balances'], dict):
                        for chain_name, balance_info in asset['cross_chain_balances'].items():
                            if isinstance(balance_info, dict) and 'balance' in balance_info:
                                balance = float(balance_info.get('balance', 0.0))
                                total_asset_value += balance * price
                            else:
                                self.logger.warning(f"Invalid balance info for asset {asset.get('asset', {}).get('symbol', 'N/A')} on chain {chain_name}")

                    # Apply the filter
                    if total_asset_value >= min_value_threshold:
                        filtered_assets.append(asset)
                    # else:
                    #     self.logger.debug(f"Filtering out asset {asset.get('asset', {}).get('symbol', 'N/A')} with value ${total_asset_value:.2f} (Threshold: ${min_value_threshold:.2f})")

                except (ValueError, TypeError) as ve:
                    self.logger.warning(f"Error processing asset during filtering (skipping asset): {asset.get('asset', {}).get('symbol', 'N/A')} - {ve}")
                    continue

            # --- Construct Final Result ---
            result_package = {
                "wallets_queried": wallets,
                "chains_queried": chains,
                "api_reported_total_balance": api_reported_total,
                "original_asset_count": len(original_assets),
                "filtered_asset_count": len(filtered_assets),
                "min_value_threshold": min_value_threshold,
                "assets": filtered_assets
            }
            self.logger.info(f"Mobula fetch complete. Original assets: {len(original_assets)}, Filtered assets (>= ${min_value_threshold:.2f}): {len(filtered_assets)}")
            return result_package

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error fetching Mobula /portfolio data: {e}")
            return None
        except Exception as e:
            # Catch potential JSON decoding errors or other unexpected issues
            self.logger.error(f"Unexpected error processing Mobula /portfolio response: {e}")
            return None

    # Removed get_wallet_holdings, get_portfolio_holdings, format_holdings_message, generate_portfolio_chart
    # These will be handled by a separate analysis/presentation class.

# test this function
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO) # Add basic logging for test
    fetcher = PortfolioFetcher()
    # Example EVM wallets
    wallets_to_test = ["6EXXKyEz5ZWNPzi1jdv3GJ86WjYC6uYRoCAz9YMYQLMG", "DXm7q65Grad9fAkWVkVCDwt1RJX1ARkntH964cS1FdYd"]
    # chains_to_test = ["Ethereum", "Base"] # Optional: Test with specific chains
    chains_to_test = None # Test fetching all chains

    # Fetch portfolio data with default threshold ($1.0)
    print("\n--- Fetching with default threshold ($1.0) ---")
    portfolio_data_default = asyncio.run(fetcher.fetch_mobula_portfolio_data(wallets_to_test, chains_to_test))

    if portfolio_data_default:
        print(f"Wallets Queried: {portfolio_data_default['wallets_queried']}")
        print(f"Chains Queried: {portfolio_data_default['chains_queried']}")
        print(f"API Reported Total: {portfolio_data_default['api_reported_total_balance']}")
        print(f"Original Assets: {portfolio_data_default['original_asset_count']}")
        print(f"Filtered Assets: {portfolio_data_default['filtered_asset_count']}")
        print(f"Threshold: {portfolio_data_default['min_value_threshold']}")
        # print("Filtered Assets List:")
        # import json
        # print(json.dumps(portfolio_data_default['assets'], indent=2)) # Pretty print assets if needed
    else:
        print("Failed to fetch portfolio data (default threshold).")

    # Fetch portfolio data with higher threshold ($100.0)
    print("\n--- Fetching with higher threshold ($100.0) ---")
    higher_threshold = 100.0
    portfolio_data_high = asyncio.run(fetcher.fetch_mobula_portfolio_data(wallets_to_test, chains_to_test, min_value_threshold=higher_threshold))

    if portfolio_data_high:
        print(f"Wallets Queried: {portfolio_data_high['wallets_queried']}")
        print(f"Chains Queried: {portfolio_data_high['chains_queried']}")
        print(f"API Reported Total: {portfolio_data_high['api_reported_total_balance']}")
        print(f"Original Assets: {portfolio_data_high['original_asset_count']}")
        print(f"Filtered Assets: {portfolio_data_high['filtered_asset_count']}")
        print(f"Threshold: {portfolio_data_high['min_value_threshold']}")
    else:
        print(f"Failed to fetch portfolio data (threshold ${higher_threshold}).")
