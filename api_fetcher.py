from typing import Dict, List, Optional, Any
import asyncio
import logging
import aiohttp # Use aiohttp for async requests
import base64 # Added for Zerion Auth
from config import Config
from enum import Enum

class ZerionPositionFilter(Enum):
    """
    Defines the types of position filters available for the Zerion portfolio endpoint.
    """
    SIMPLE = "only_simple"  # Default: Tokens, NFTs, etc. Excludes complex positions.
    LOCKED = "only_complex"  # Positions that are locked (e.g., vested tokens, staked assets with lockups).
    # You could add other Zerion supported filters here if needed, e.g.:
    # NO_FILTER = "no_filter" # All positions
    # COMPLEX = "only_complex" # Liquidity pools, staking, lending, etc.
    # CLAIMABLE = "only_claimable" # Claimable rewards or assets

class PortfolioFetcher:
    """Handles fetching raw portfolio data using Mobula API and pre-filtering."""

    def __init__(self):
        self.config = Config()
        self.mobula_base_url = "https://api.mobula.io/api/1" # Base for Mobula
        self.mobula_api_key = self.config.MOBULA_API_KEY
        
        # Zerion API
        self.zerion_base_url = "https://api.zerion.io/v1"
        self.zerion_api_key = self.config.ZERION_API_KEY
        
        self.cmc_base_url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency" # CMC v2 base
        self.cmc_api_key = self.config.COINMARKETCAP_API_KEY
        
        self.logger = logging.getLogger(__name__)

    async def fetch_mobula_portfolio_data(
        self,
        wallets: List[str],
        chains: Optional[List[str]] = None,
        min_value_threshold: float = 1.0
    ) -> Optional[Dict[str, Any]]:
        """
        Fetches portfolio data from Mobula API asynchronously, filters assets by minimum total value,
        and returns a structured dictionary.
        """
        # ... (existing Mobula fetch logic remains unchanged) ...
        if not self.mobula_api_key:
            self.logger.error("MOBULA_API_KEY is not configured.")
            return None
        if not wallets:
            self.logger.warning("fetch_mobula_portfolio_data called with no wallets.")
            return None

        url = f"{self.mobula_base_url}/wallet/portfolio"
        params_wallets_str = ",".join(wallets)
        params_chains_str = ",".join(chains) if chains else None
        params = {
            "wallets": params_wallets_str,
            "blockchains": params_chains_str,
            "filterSpam": "true",
            "liqmin": 1000,
            "unlistedAssets": "true",
        }
        params = {k: v for k, v in params.items() if v is not None}
        request_headers = {"Authorization": self.mobula_api_key, "User-Agent": "PortfolioTrackerBot/1.0"}
        
        self.logger.info(f"Fetching Mobula /wallet/portfolio (async): wallets_count={len(wallets)}, params={params}")
        try:
            async with aiohttp.ClientSession(headers=request_headers, timeout=aiohttp.ClientTimeout(total=20)) as session:
                async with session.get(url, params=params) as response:
                    response.raise_for_status()
                    raw_data = await response.json()
            # ... (rest of Mobula processing logic) ...
            if not isinstance(raw_data, dict) or 'data' not in raw_data or not isinstance(raw_data['data'], dict):
                self.logger.error(f"Invalid Mobula response structure (missing top-level 'data' dict): {raw_data}")
                return None
            data_block = raw_data['data']
            original_assets = data_block.get('assets')
            api_reported_total = data_block.get('total_wallet_balance')
            if not isinstance(original_assets, list):
                self.logger.error(f"Invalid Mobula response structure (missing or invalid 'assets' list): {raw_data}")
                return { "wallets_queried": wallets, "chains_queried": chains, "api_reported_total_balance": api_reported_total,
                         "original_asset_count": 0, "filtered_asset_count": 0, "min_value_threshold": min_value_threshold, "assets": [] }
            filtered_assets = []
            for asset in original_assets:
                try:
                    if not isinstance(asset, dict) or 'price' not in asset or 'cross_chain_balances' not in asset:
                        self.logger.warning(f"Skipping asset with unexpected structure: {asset.get('asset', {}).get('symbol', 'N/A')}")
                        continue
                    price = float(asset.get('price', 0.0))
                    total_asset_value = 0.0
                    if isinstance(asset['cross_chain_balances'], dict):
                        for chain_name_key, balance_info in asset['cross_chain_balances'].items():
                            if isinstance(balance_info, dict) and 'balance' in balance_info:
                                balance = float(balance_info.get('balance', 0.0))
                                total_asset_value += balance * price
                    if total_asset_value >= min_value_threshold:
                        filtered_assets.append(asset)
                except (ValueError, TypeError) as ve:
                    self.logger.warning(f"Error processing asset during filtering: {asset.get('asset', {}).get('symbol', 'N/A')} - {ve}")
            result_package = { "wallets_queried": wallets, "chains_queried": chains, "api_reported_total_balance": api_reported_total,
                               "original_asset_count": len(original_assets), "filtered_asset_count": len(filtered_assets),
                               "min_value_threshold": min_value_threshold, "assets": filtered_assets }
            self.logger.info(f"Mobula fetch complete. Original: {len(original_assets)}, Filtered (>= ${min_value_threshold:.2f}): {len(filtered_assets)}")
            return result_package
        except aiohttp.ClientResponseError as e:
            self.logger.error(f"Error fetching Mobula /portfolio data (aiohttp status: {e.status}, message: {e.message}) for URL: {e.request_info.url}")
            return None
        except aiohttp.ClientError as e:
            self.logger.error(f"AIOHTTP client error fetching Mobula /portfolio data: {e}")
            return None
        except asyncio.TimeoutError:
            self.logger.error(f"AIOHTTP request to Mobula timed out after 20 seconds for URL: {url} with params: {params}")
            return None
        except Exception as e:
            self.logger.exception(f"Unexpected error processing Mobula /portfolio response (async): {e}")
            return None


    # --- CoinMarketCap API Methods ---
    async def fetch_cmc_token_quotes(
        self, 
        ids: Optional[List[int]] = None, 
        slugs: Optional[List[str]] = None, 
        symbols: Optional[List[str]] = None,
        convert: str = "USD"
    ) -> Optional[Dict[str, Any]]:
        # ... (existing CMC fetch_cmc_token_quotes logic remains unchanged) ...
        if not self.cmc_api_key:
            self.logger.error("COINMARKETCAP_API_KEY is not configured.")
            return None
        if not (ids or slugs or symbols):
            self.logger.error("fetch_cmc_token_quotes requires at least one of ids, slugs, or symbols.")
            return None
        url = f"{self.cmc_base_url}/quotes/latest"
        params = {"convert": convert, "aux": "num_market_pairs,cmc_rank,date_added,tags,platform,max_supply,circulating_supply,total_supply,is_active,is_fiat", "skip_invalid": "true"}
        identifier_type, identifier_value = "", ""
        if ids: params["id"], identifier_type, identifier_value = ",".join(map(str, ids)), "IDs", params["id"]
        elif slugs: params["slug"], identifier_type, identifier_value = ",".join(slugs), "Slugs", params["slug"]
        elif symbols: params["symbol"], identifier_type, identifier_value = ",".join(symbols), "Symbols", params["symbol"]
        headers = {"Accepts": "application/json", "X-CMC_PRO_API_KEY": self.cmc_api_key}
        self.logger.info(f"Fetching CMC /quotes/latest for {identifier_type}: {identifier_value}")
        try:
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.get(url, params=params) as response:
                    self.logger.debug(f"CMC API request to {response.url} status: {response.status}")
                    raw_data = await response.json()
                    if response.status != 200:
                        status_info = raw_data.get("status", {})
                        self.logger.error(f"CMC API error ({status_info.get('error_code', response.status)}): {status_info.get('error_message', 'Unknown CMC API error')} for {identifier_type} {identifier_value}. URL: {response.url}")
                        return None
            if isinstance(raw_data, dict) and "data" in raw_data:
                self.logger.info(f"Successfully fetched quotes from CMC for {len(raw_data['data'])} requested identifiers.")
                return raw_data["data"]
            else:
                self.logger.error(f"Unexpected CMC /quotes/latest response structure for {identifier_type} {identifier_value}. Data: {str(raw_data)[:500]}")
                return None
        except Exception as e:
            self.logger.exception(f"Error during CMC /quotes/latest request for {identifier_type} {identifier_value}: {e}")
            return None


    async def get_token_info_by_contract_address(
        self, 
        contract_address: str,
    ) -> Optional[Dict[str, Any]]:
        # ... (existing CMC get_token_info_by_contract_address logic remains unchanged) ...
        if not self.cmc_api_key:
            self.logger.error("COINMARKETCAP_API_KEY is not configured.")
            return None
        if not contract_address:
            self.logger.error("get_token_info_by_contract_address requires a contract_address.")
            return None
        url = f"{self.cmc_base_url}/info"
        params = {"address": contract_address}
        headers = {"Accepts": "application/json", "X-CMC_PRO_API_KEY": self.cmc_api_key}
        self.logger.info(f"Fetching CMC /info for contract address: {contract_address}")
        try:
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as session:
                async with session.get(url, params=params) as response:
                    self.logger.debug(f"CMC API request to {response.url} status: {response.status}")
                    raw_data = await response.json()
                    if response.status != 200:
                        status_info = raw_data.get("status", {})
                        self.logger.error(f"CMC API error ({status_info.get('error_code', response.status)}) for /info address {contract_address}: {status_info.get('error_message', 'Unknown CMC API error')}. URL: {response.url}")
                        return None
            if isinstance(raw_data, dict) and "data" in raw_data and isinstance(raw_data["data"], dict):
                data_map = raw_data["data"]
                if not data_map:
                    self.logger.warning(f"CMC /info for address {contract_address} returned empty data map.")
                    return None
                first_cmc_id = next(iter(data_map))
                token_info = data_map.get(first_cmc_id)
                if token_info and isinstance(token_info, dict) and 'slug' in token_info:
                    self.logger.info(f"Successfully fetched info from CMC for address {contract_address}. Token: {token_info.get('name')}, Slug: {token_info.get('slug')}")
                    return token_info
                else:
                    self.logger.warning(f"CMC /info for address {contract_address} did not return expected token data structure or slug. Data: {str(data_map)[:500]}")
                    return None
            else:
                self.logger.error(f"Unexpected CMC /info response structure for address {contract_address}. Data: {str(raw_data)[:500]}")
                return None
        except Exception as e:
            self.logger.exception(f"Unexpected error during CMC /info request for address {contract_address}: {e}")
            return None


    async def fetch_zerion_evm_portfolio_data(
        self,
        evm_address: str,
        chains_filter: Optional[List[str]] = None,  # e.g., ["ethereum", "polygon"]
        position_type_filter: ZerionPositionFilter = ZerionPositionFilter.SIMPLE
    ) -> Optional[Dict[str, Any]]:
        """
        Fetches portfolio data for a given EVM address using Zerion API.
        Targets the /v1/wallets/{address}/portfolio endpoint.
        Returns the raw API JSON response if successful and is a dictionary.

        Args:
            evm_address: The EVM wallet address.
            chains_filter: Optional list of Zerion chain IDs to filter by.
            position_type_filter: Determines the type of positions to fetch.
                Defaults to ZerionPositionFilter.SIMPLE (only_simple).
                Use ZerionPositionFilter.LOCKED for locked/vested positions.

        Returns:
            The API JSON response as a dictionary if the request is successful and
            the response is a JSON object. Returns None on error, if data is not
            ready (HTTP 202), if the resource is not found (HTTP 404), or if the
            API response is not a JSON dictionary.
        """

        url = f"{self.zerion_base_url}/wallets/{evm_address}/portfolio"
        params: Dict[str, Any] = {
            "filter[positions]": position_type_filter.value,
            "currency": "usd"  # Request values in USD
            # Add pagination params later if needed: page[size], page[before], page[after]
        }
        if chains_filter:
            params["filter[chain_ids]"] = ",".join(chains_filter)

        auth_header = {
            "accept": "application/json",
            "authorization": self.zerion_api_key
        }
        self.logger.info(f"Fetching Zerion /portfolio for address: {evm_address}, params: {params}")

        try:
            async with aiohttp.ClientSession(headers=auth_header, timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.get(url, params=params) as response:
                    self.logger.debug(f"Zerion API request to {response.url} status: {response.status}")

                    if response.status == 202:  # Accepted, data not ready yet
                        self.logger.info(f"Zerion API returned 202 for {evm_address} using /portfolio. Data is being prepared. No JSON content to return.")
                        return None

                    response.raise_for_status() # Raises aiohttp.ClientResponseError for 4xx/5xx status codes

                    api_response_content: Any = await response.json()

                    if not isinstance(api_response_content, dict):
                        self.logger.error(
                            f"Unexpected Zerion /portfolio response structure for {evm_address}. "
                            f"Expected a JSON dictionary, but got {type(api_response_content)}. "
                            f"Data: {str(api_response_content)[:500]}"
                        )
                        return None

                    return api_response_content

        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                self.logger.info(f"Zerion API returned 404 for {evm_address} using /portfolio (wallet not found or no matching positions). URL: {e.request_info.url}")
                return None
            self.logger.error(f"Zerion API error ({e.status}) for /portfolio {evm_address}: {e.message}. URL: {e.request_info.url}")
            return None
        except aiohttp.ClientError as e:
            self.logger.error(f"AIOHTTP client error fetching Zerion /portfolio for {evm_address}: {e}")
            return None
        except asyncio.TimeoutError:
            self.logger.error(f"Request to Zerion /portfolio timed out for {evm_address}. URL: {url}")
            return None
        except Exception as e:
            self.logger.exception(f"Unexpected error during Zerion /portfolio request for {evm_address}: {e}")
            return None

if __name__ == "__main__":
    import json 
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    async def main_test():
        fetcher = PortfolioFetcher()
        

        # Test Zerion (ensure ZERION_API_KEY is set)
        if not fetcher.zerion_api_key:
            print("ZERION_API_KEY not found. Please set it in your .env file or environment.")
            return
        
        # Replace with a test EVM address that has some positions
        test_evm_address = "0xCe100d94EA22aAb119633D434BdEEA26F4244d1a" # vitalik.eth
        position_type_filter = ZerionPositionFilter.LOCKED  # Change to LOCKED if you want locked positions
        # test_evm_address = "0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae" # Another example
        print(f"\n--- Testing fetch_zerion_evm_portfolio_data for address: {test_evm_address} ---")
        zerion_data = await fetcher.fetch_zerion_evm_portfolio_data(test_evm_address, position_type_filter=ZerionPositionFilter.SIMPLE)
        if zerion_data is not None:
            print(f"Fetched {len(zerion_data)} assets from Zerion.")
            print(json.dumps(zerion_data, indent=2))
            # Save to file (optional)
            # with open("zerion_portfolio_test.json", "w") as json_file:
            #     json.dump(zerion_data, json_file, indent=4)
            # print("Test Zerion data saved to zerion_portfolio_test.json")
        else:
            print(f"Failed to fetch Zerion data for {test_evm_address} or an error occurred.")

    asyncio.run(main_test())
