from typing import Dict, List, Optional, Any
import asyncio
import logging
import aiohttp # Use aiohttp for async requests
import base64 # Added for Zerion Auth
from config import Config
from enum import Enum
import json

class ZerionPositionFilter(Enum):
    """
    Defines the types of position filters available for the Zerion portfolio endpoint.
    """
    SIMPLE = "only_simple"  # Default: Tokens, NFTs, etc. Excludes complex positions.
    LOCKED = "only_complex"  # Positions that are locked (e.g., vested tokens, staked assets with lockups).
    NO_FILTER = "no_filter" # All positions
    COMPLEX = "only_complex" # Liquidity pools, staking, lending, etc.

class ZerionTrashFilter(Enum):
    """
    Defines how to filter positions based on the 'is_trash' flag.
    """
    ONLY_TRASH = "only_trash"
    ONLY_NON_TRASH = "only_non_trash"
    INCLUDE_TRASH = "include_trash"

class PortfolioFetcher:
    """Handles fetching raw portfolio data using various APIs."""

    def __init__(self):
        self.config = Config()
        self.mobula_base_url = "https://api.mobula.io/api/1" # Base for Mobula
        
        # Zerion API
        self.zerion_base_url = "https://api.zerion.io/v1"
        self.zerion_api_key = self.config.ZERION_API_KEY
        
        self.cmc_base_url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency" # CMC v2 base
        self.cmc_api_key = self.config.COINMARKETCAP_API_KEY

        # --- NEW: CoinGecko API ---
        self.coingecko_base_url = "https://api.coingecko.com/api/v3"
        self.coingecko_api_key = self.config.COINGECKO_API_KEY
        self.coingecko_semaphore = asyncio.Semaphore(5) # Limit to 5 concurrent CoinGecko requests
        self.coingecko_request_delay = 1 # Delay between requests to respect rate limits (1 second per request)
        
        self.logger = logging.getLogger(__name__)

    async def fetch_zerion_wallet_summary(self, address: str) -> Optional[Dict[str, Any]]:
        """
        Fetches a high-level portfolio summary for a given EVM address using Zerion API.
        
        Args:
            address: The EVM wallet address.

        Returns:
            The 'data' object from the API response, or None on failure.
        """
        if not self.zerion_api_key:
            self.logger.error("ZERION_API_KEY is not configured.")
            return None

        url = f"{self.zerion_base_url}/wallets/{address}/portfolio"
        
        params: Dict[str, Any] = {
            "filter[positions]": "no_filter",
            "currency": "usd"
        }

        headers = {
            "accept": "application/json",
            "authorization": self.zerion_api_key
        }
        
        self.logger.info(f"Fetching Zerion /portfolio summary for address: {address}")

        try:
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.get(url, params=params) as response:
                    self.logger.debug(f"Zerion API request to {response.url} status: {response.status}")
                    response.raise_for_status()
                    api_response = await response.json()
                    
                    if isinstance(api_response, dict) and "data" in api_response:
                        self.logger.info(f"Successfully fetched portfolio summary from Zerion for {address}.")
                        return api_response["data"]
                    else:
                        self.logger.error(f"Unexpected Zerion /portfolio response structure for {address}. Data: {str(api_response)[:500]}")
                        return None
                        
        except aiohttp.ClientResponseError as e:
            self.logger.error(f"Zerion API error ({e.status}) for /portfolio summary {address}: {e.message}. URL: {e.request_info.url}")
            return None
        except Exception as e:
            self.logger.exception(f"Unexpected error during Zerion /portfolio summary request for {address}: {e}")
            return None

    async def fetch_zerion_portfolio_data(self, address: str) -> Optional[List[Dict[str, Any]]]:
        """
        Fetches detailed portfolio positions for a given EVM address using Zerion API.
        Always fetches all position types (no_filter).
        
        Args:
            address: The EVM wallet address.

        Returns:
            A list of position objects from the API response's 'data' key, or None on failure.
        """
        if not self.zerion_api_key:
            self.logger.error("ZERION_API_KEY is not configured.")
            return None

        url = f"{self.zerion_base_url}/wallets/{address}/positions"
        
        params: Dict[str, Any] = {
            "filter[positions]": "no_filter", # Always fetch all positions
            "currency": "usd",
            "sort": "-value"
        }

        headers = {
            "accept": "application/json",
            "authorization": self.zerion_api_key
        }
        
        self.logger.info(f"Fetching Zerion /positions (detailed) for address: {address}, params: {params}")

        try:
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.get(url, params=params) as response:
                    self.logger.debug(f"Zerion API request to {response.url} status: {response.status}")
                    response.raise_for_status()
                    api_response = await response.json()
                    
                    if isinstance(api_response, dict) and "data" in api_response and isinstance(api_response["data"], list):
                        self.logger.info(f"Successfully fetched {len(api_response['data'])} detailed positions from Zerion for {address}.")
                        return api_response["data"]
                    else:
                        self.logger.error(f"Unexpected Zerion /positions response structure for {address}. Data: {str(api_response)[:500]}")
                        return None
                        
        except aiohttp.ClientResponseError as e:
            self.logger.error(f"Zerion API error ({e.status}) for /positions {address}: {e.message}. URL: {e.request_info.url}")
            return None
        except Exception as e:
            self.logger.exception(f"Unexpected error during Zerion /positions request for {address}: {e}")
            return None

    async def fetch_mobula_portfolio_data(
        self,
        wallets: List[str],
        chains: Optional[List[str]] = None,
        min_value_threshold: float = 1.0
    ) -> Optional[Dict[str, Any]]:
        """
        DEPRECATED: This function is being replaced by Zerion API integration for the /view command.
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
        if not self.cmc_api_key:
            self.logger.error("COINMARKETCAP_API_KEY is not configured.")
            return None
        if not (ids or slugs or symbols):
            self.logger.error("fetch_cmc_token_quotes requires at least one of ids, slugs, or symbols.")
            return None
        url = f"{self.cmc_base_url}/quotes/latest"
        params = {"convert": convert, "aux": "num_market_pairs,cmc_rank,date_added,tags,platform,max_supply,circulating_supply,total_supply,is_active,is_fiat", "skip_invalid": "true"}
        
        identifier_type = ""
        identifier_value = ""
        
        if ids:
            params["id"] = ",".join(map(str, ids))
            identifier_type = "IDs"
            identifier_value = params["id"]
        elif slugs:
            params["slug"] = ",".join(slugs)
            identifier_type = "Slugs"
            identifier_value = params["slug"]
        elif symbols:
            params["symbol"] = ",".join(symbols)
            identifier_type = "Symbols"
            identifier_value = params["symbol"]
            
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


    async def get_cmc_token_details(self, identifier: str) -> Optional[Dict[str, Any]]:
        """
        Fetches token details from CoinMarketCap, automatically handling if the
        identifier is a symbol or a contract address.

        Args:
            identifier: The token symbol (case-insensitive) or contract address.

        Returns:
            A dictionary containing the token's data from the CMC quotes endpoint,
            or None if not found or an error occurs.
        """
        # Heuristic to check if the identifier is likely a contract address.
        is_evm_address = identifier.startswith('0x') and len(identifier) == 42
        is_solana_like_address = 43 <= len(identifier) <= 44 and identifier.isalnum()
        is_sui_like_address = '::' in identifier and identifier.startswith('0x')

        if is_evm_address:
            self.logger.info(f"Identifier '{identifier}' detected as an EVM contract address.")
            # Use the /info endpoint to find the token by address
            token_info_by_address = await self.get_token_info_by_contract_address(identifier)
            if not token_info_by_address or 'id' not in token_info_by_address:
                self.logger.warning(f"Could not resolve EVM address '{identifier}' to a CMC token ID.")
                return None # This will trigger the CoinGecko fallback in the handler
            
            # Now use the resolved CMC ID to get the full quote data
            cmc_id = token_info_by_address['id']
            self.logger.info(f"EVM address '{identifier}' resolved to CMC ID {cmc_id}. Fetching quote.")
            quotes_data = await self.fetch_cmc_token_quotes(ids=[cmc_id])
            
            if quotes_data and str(cmc_id) in quotes_data:
                return quotes_data[str(cmc_id)]
            else:
                self.logger.warning(f"Failed to fetch quote for CMC ID {cmc_id} after resolving from EVM address.")
                return None
        
        elif is_solana_like_address or is_sui_like_address:
            # For non-EVM addresses, CMC's direct lookup is less reliable.
            # Skip the CMC check to use the CoinGecko fallback in the handler.
            self.logger.info(f"Identifier '{identifier}' detected as a non-EVM address. Skipping CMC check.")
            return None

        else:
            # Treat as a symbol
            symbol = identifier.upper()
            self.logger.info(f"Identifier '{identifier}' treated as a symbol. Querying CMC with '{symbol}'.")
            
            quotes_data = await self.fetch_cmc_token_quotes(symbols=[symbol])
            
            if quotes_data:
                if symbol in quotes_data:
                    token_data_list = quotes_data[symbol]
                    if isinstance(token_data_list, list) and token_data_list:
                        if len(token_data_list) > 1:
                            self.logger.warning(f"Multiple tokens found for symbol '{symbol}'. Using the first result.")
                        return token_data_list[0]
                    elif isinstance(token_data_list, dict):
                        return token_data_list
                
                self.logger.warning(f"No token data found for symbol '{symbol}' in the main data keys of CMC response.")
                for key, value in quotes_data.items():
                    if isinstance(value, list) and value and value[0].get('symbol', '').upper() == symbol:
                        self.logger.info(f"Found matching token for symbol '{symbol}' via iteration.")
                        return value[0]
                    elif isinstance(value, dict) and value.get('symbol', '').upper() == symbol:
                         self.logger.info(f"Found matching token for symbol '{symbol}' via iteration.")
                         return value

            self.logger.warning(f"No token data ultimately found for symbol '{symbol}' in CMC response.")
            return None

    async def get_token_info_by_contract_address(
        self, 
        contract_address: str,
    ) -> Optional[Dict[str, Any]]:
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

    # --- CoinGecko API Methods ---
    async def _fetch_coingecko_batch(self, session: aiohttp.ClientSession, network_id: str, addresses_batch: List[str]) -> Dict[str, Any]:
        """Helper to fetch a single batch of CoinGecko token prices."""
        # Addresses for chains like Solana are case-sensitive, so do not convert to lowercase.
        addresses_str = ",".join(addresses_batch)
        url = f"{self.coingecko_base_url}/onchain/simple/networks/{network_id}/token_price/{addresses_str}"
        
        params = {
            "include_market_cap": "true",
            "mcap_fdv_fallback": "true"
        }
        
        headers = {
            "accept": "application/json",
            "x-cg-demo-api-key": self.coingecko_api_key
        }
        
        self.logger.info(f"Fetching CoinGecko /token_price for network '{network_id}' and {len(addresses_batch)} address(es).")

        async with self.coingecko_semaphore: # Acquire semaphore before making request
            try:
                async with session.get(url, params=params, headers=headers) as response:
                    self.logger.debug(f"CoinGecko API request to {response.url} status: {response.status}")
                    response.raise_for_status()
                    api_response = await response.json()
                    
                    if isinstance(api_response, dict) and 'data' in api_response:
                        token_prices = api_response.get('data', {}).get('attributes', {}).get('token_prices')
                        if isinstance(token_prices, dict):
                            self.logger.info(f"Successfully fetched prices from CoinGecko for {len(token_prices)} tokens on network {network_id}.")
                            return token_prices
                    
                    self.logger.error(f"Unexpected CoinGecko response structure or missing token_prices. Data: {str(api_response)[:500]}")
                    return {} # Return empty dict on unexpected structure

            except aiohttp.ClientResponseError as e:
                self.logger.error(f"CoinGecko API error ({e.status}) for network {network_id}: {e.message}. URL: {e.request_info.url}")
                return {}
            except Exception as e:
                self.logger.exception(f"Unexpected error during CoinGecko /token_price request for network {network_id}: {e}")
                return {}
            finally:
                await asyncio.sleep(self.coingecko_request_delay) # Delay after each request

    async def fetch_coingecko_token_price(
        self, 
        network_id: str, 
        token_addresses: List[str],
        batch_size: int = 50 # CoinGecko recommends max 50 addresses per request
    ) -> Optional[Dict[str, Any]]:
        """
        Fetches token prices from the CoinGecko on-chain API for a given network, with batching.

        Args:
            network_id: The CoinGecko network ID (e.g., 'eth', 'polygon_pos').
            token_addresses: A list of token contract addresses.
            batch_size: The maximum number of addresses to include in a single API request.

        Returns:
            A dictionary mapping lowercase token addresses to their price data, or None on failure.
        """
        if not network_id or not token_addresses:
            self.logger.error("fetch_coingecko_token_price requires a network_id and at least one token address.")
            return None

        all_prices: Dict[str, Any] = {}
        
        # Create a single session for all batches
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session: # Increased timeout for multiple batches
            tasks = []
            for i in range(0, len(token_addresses), batch_size):
                batch = token_addresses[i:i + batch_size]
                tasks.append(self._fetch_coingecko_batch(session, network_id, batch))
            
            # Run all batch fetches concurrently
            results = await asyncio.gather(*tasks)
            
            for batch_result in results:
                all_prices.update(batch_result) # Merge results from all batches

        if not all_prices:
            self.logger.warning(f"No prices fetched for any of the {len(token_addresses)} tokens on network {network_id}.")
            return None
        
        return all_prices

    async def _fetch_coingecko_price_by_id(self, coin_id: str) -> Optional[float]:
        """Fetches price from CoinGecko's /simple/price endpoint using the coingecko_coin_id."""
        if not coin_id:
            return None

        url = f"{self.coingecko_base_url}/simple/price"
        params = {"ids": coin_id, "vs_currencies": "usd"}
        headers = {"accept": "application/json", "x-cg-demo-api-key": self.coingecko_api_key}
        
        self.logger.info(f"Fetching CoinGecko /simple/price for coin_id: '{coin_id}'")
        async with self.coingecko_semaphore:
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
                    async with session.get(url, params=params, headers=headers) as response:
                        response.raise_for_status()
                        api_response = await response.json()
                        if coin_id in api_response and "usd" in api_response[coin_id]:
                            price = api_response[coin_id]["usd"]
                            self.logger.info(f"Successfully fetched price for {coin_id}: ${price}")
                            return float(price)
                        self.logger.warning(f"Could not find USD price for coin_id '{coin_id}' in /simple/price response.")
                        return None
            except Exception as e:
                self.logger.exception(f"Error fetching price by coin_id '{coin_id}': {e}")
                return None
            finally:
                await asyncio.sleep(self.coingecko_request_delay)

    async def fetch_coingecko_token_details(
        self,
        network_id: str,
        token_address: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fetches detailed token information from CoinGecko, with a fallback for tokens without direct USD price.
        """
        if not network_id or not token_address:
            self.logger.error("fetch_coingecko_token_details requires a network_id and a token_address.")
            return None

        url = f"{self.coingecko_base_url}/onchain/networks/{network_id}/tokens/{token_address}"
        headers = {"accept": "application/json", "x-cg-demo-api-key": self.coingecko_api_key}
        
        self.logger.info(f"Fetching CoinGecko token details for address '{token_address}' on network '{network_id}'.")

        async with self.coingecko_semaphore:
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                    async with session.get(url, headers=headers) as response:
                        response.raise_for_status()
                        api_response = await response.json()
                        
                        if isinstance(api_response, dict) and 'data' in api_response:
                            attributes = api_response.get('data', {}).get('attributes', {})
                            if attributes:
                                name = attributes.get('name')
                                symbol = attributes.get('symbol')
                                price_usd_str = attributes.get('price_usd')
                                coingecko_coin_id = attributes.get('coingecko_coin_id')

                                if not (name and symbol):
                                    self.logger.warning("Response missing name or symbol.")
                                    return None

                                price_usd = None
                                # If price is present and valid, use it
                                if price_usd_str is not None:
                                    try:
                                        price_usd = float(price_usd_str)
                                    except (ValueError, TypeError):
                                        self.logger.warning(f"Could not parse price_usd '{price_usd_str}'. Will attempt fallback.")
                                
                                # If price is still None and we have a coin_id, use the fallback
                                if price_usd is None and coingecko_coin_id:
                                    self.logger.info(f"No direct price for {name}. Using fallback with coin_id '{coingecko_coin_id}'.")
                                    price_usd = await self._fetch_coingecko_price_by_id(coingecko_coin_id)

                                if price_usd is not None:
                                    self.logger.info(f"Successfully resolved details for {name} ({symbol}) on {network_id}.")
                                    return {"name": name, "symbol": symbol, "price_usd": price_usd}

                        self.logger.error(f"Could not resolve price for token. Final attempt failed. Data: {str(api_response)[:500]}")
                        return None

            except aiohttp.ClientResponseError as e:
                self.logger.error(f"CoinGecko API error ({e.status}) for token details on network {network_id}: {e.message}. URL: {e.request_info.url}")
                return None
            except Exception as e:
                self.logger.exception(f"Unexpected error during CoinGecko token details request for network {network_id}: {e}")
                return None
            finally:
                await asyncio.sleep(self.coingecko_request_delay)


    async def zerion_portfolio_data(
        self,
        evm_address: str,
        chains_filter: Optional[List[str]] = None,  # e.g., ["ethereum", "polygon"]
        position_filter: ZerionPositionFilter = ZerionPositionFilter.SIMPLE
    ) -> Optional[Dict[str, Any]]:
        """
        Fetches portfolio data for a given EVM address using Zerion API.
        Targets the /v1/wallets/{address}/portfolio endpoint.
        Returns the raw API JSON response if successful and is a dictionary.
        """
        if not self.zerion_api_key:
            self.logger.error("ZERION_API_KEY is not configured.")
            return None

        url = f"{self.zerion_base_url}/wallets/{evm_address}/portfolio"
        params: Dict[str, Any] = {
            "filter[positions]": position_filter.value,
            "currency": "usd"
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

                    if response.status == 202:
                        self.logger.info(f"Zerion API returned 202 for {evm_address} using /portfolio. Data is being prepared.")
                        return None

                    response.raise_for_status()

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
        except Exception as e:
            self.logger.exception(f"Unexpected error during Zerion /portfolio request for {evm_address}: {e}")
            return None
        
    async def zerion_positions_data(
        self,
        evm_address: str,
        position_filter: ZerionPositionFilter = ZerionPositionFilter.SIMPLE,
        trash_filter: ZerionTrashFilter = ZerionTrashFilter.ONLY_NON_TRASH,
        chain_filter: Optional[List[str]] = None,
        sort_by: str = 'value'
    ) -> Optional[Dict[str, Any]]:
        """
        Fetches a list of wallet positions from the Zerion API.
        """
        if not self.zerion_api_key:
            self.logger.error("ZERION_API_KEY is not configured.")
            return None

        url = f"{self.zerion_base_url}/wallets/{evm_address}/positions"
        params = {
            "filter[positions]": position_filter.value,
            "filter[trash]": trash_filter.value,
            "sort": sort_by,
            "currency": "usd"
        }
        if chain_filter:
            params["filter[chain_ids]"] = ",".join(chain_filter)

        auth_header = {
            "accept": "application/json",
            "authorization": self.zerion_api_key
        }
        self.logger.info(f"Fetching Zerion /positions for address: {evm_address}, params: {params}")

        try:
            async with aiohttp.ClientSession(headers=auth_header, timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.get(url, params=params) as response:
                    self.logger.debug(f"Zerion API request to {response.url} status: {response.status}")
                    response.raise_for_status()
                    return await response.json()
        except aiohttp.ClientResponseError as e:
            self.logger.error(f"Zerion API error ({e.status}) for /positions {evm_address}: {e.message}. URL: {e.request_info.url}")
            return None
        except Exception as e:
            self.logger.exception(f"Unexpected error during Zerion /positions request for {evm_address}: {e}")
            return None
        
    async def zerion_pnl_data(
        self,
        evm_address: str,
        chains_filter: Optional[List[str]] = None  # e.g., ["ethereum", "polygon"]
    ) -> Optional[Dict[str, Any]]:
        """
        Fetches profit and loss (PnL) data for a given EVM address using Zerion API.
        Targets the /v1/wallets/{address}/pnl endpoint.
        """
        if not self.zerion_api_key:
            self.logger.error("ZERION_API_KEY is not configured.")
            return None

        url = f"{self.zerion_base_url}/wallets/{evm_address}/pnl"
        params: Dict[str, Any] = {
            "currency": "usd"
        }
        if chains_filter:
            params["filter[chain_ids]"] = ",".join(chains_filter)

        auth_header = {
            "accept": "application/json",
            "authorization": self.zerion_api_key
        }
        self.logger.info(f"Fetching Zerion /pnl for address: {evm_address}, params: {params}")

        try:
            async with aiohttp.ClientSession(headers=auth_header, timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.get(url, params=params) as response:
                    self.logger.debug(f"Zerion API request to {response.url} status: {response.status}")

                    if response.status == 202:
                        self.logger.info(f"Zerion API returned 202 for {evm_address} using /pnl. Data is being prepared.")
                        return None

                    response.raise_for_status()

                    api_response_content: Any = await response.json()

                    if not isinstance(api_response_content, dict):
                        self.logger.error(
                            f"Unexpected Zerion /pnl response structure for {evm_address}. "
                            f"Expected a JSON dictionary, but got {type(api_response_content)}. "
                            f"Data: {str(api_response_content)[:500]}"
                        )
                        return None

                    return api_response_content

        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                self.logger.info(f"Zerion API returned 404 for {evm_address} using /pnl (wallet not found or no PnL data). URL: {e.request_info.url}")
                return None
            self.logger.error(f"Zerion API error ({e.status}) for /pnl {evm_address}: {e.message}. URL: {e.request_info.url}")
            return None
        except Exception as e:
            self.logger.exception(f"Unexpected error during Zerion /pnl request for {evm_address}: {e}")
            return None
        
    async def zerion_wallet_chart_data(
        self,
        evm_address: str,
        chart_period: str = "month",  # Options: hour, day, week, month, year, max
        chains_filter: Optional[List[str]] = None  # e.g., ["ethereum", "polygon"]
    ) -> Optional[Dict[str, Any]]:
        """
        Fetches wallet chart data for a given EVM address using Zerion API.
        Targets the /v1/wallets/{address}/charts/{chart_period} endpoint.
        """
        if not self.zerion_api_key:
            self.logger.error("ZERION_API_KEY is not configured.")
            return None

        valid_periods = ["hour", "day", "week", "month", "year", "max"]
        if chart_period not in valid_periods:
            self.logger.error(f"Invalid chart_period: {chart_period}. Must be one of {valid_periods}")
            return None

        url = f"{self.zerion_base_url}/wallets/{evm_address}/charts/{chart_period}"
        params: Dict[str, Any] = {
            "currency": "usd"
        }
        if chains_filter:
            params["filter[chain_ids]"] = ",".join(chains_filter)

        auth_header = {
            "accept": "application/json",
            "authorization": self.zerion_api_key
        }
        self.logger.info(f"Fetching Zerion /charts/{chart_period} for address: {evm_address}, params: {params}")

        try:
            async with aiohttp.ClientSession(headers=auth_header, timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.get(url, params=params) as response:
                    self.logger.debug(f"Zerion API request to {response.url} status: {response.status}")
                    response.raise_for_status()

                    api_response_content: Any = await response.json()

                    if not isinstance(api_response_content, dict):
                        self.logger.error(
                            f"Unexpected Zerion /charts/{chart_period} response structure for {evm_address}. "
                            f"Expected a JSON dictionary, but got {type(api_response_content)}. "
                            f"Data: {str(api_response_content)[:500]}"
                        )
                        return None

                    return api_response_content

        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                self.logger.info(f"Zerion API returned 404 for {evm_address} using /charts/{chart_period} (wallet not found or no chart data). URL: {e.request_info.url}")
                return None
            self.logger.error(f"Zerion API error ({e.status}) for /charts/{chart_period} {evm_address}: {e.message}. URL: {e.request_info.url}")
            return None
        except Exception as e:
            self.logger.exception(f"Unexpected error during Zerion /charts/{chart_period} request for {evm_address}: {e}")
            return None

    async def get_wallet_transactions(self, address: str, operation_type: str = 'send') -> Optional[List[Dict[str, Any]]]:
        """
        Fetches all transactions for a given wallet address and operation type from the Zerion API.
        Handles pagination to retrieve all transactions asynchronously.
        """
        if not self.zerion_api_key:
            self.logger.error("ZERION_API_KEY is not configured.")
            return None

        all_transactions = []
        valid_operation_types = ['send', 'receive']
        if operation_type not in valid_operation_types:
            self.logger.error(f"Invalid operation_type for get_wallet_transactions: {operation_type}")
            return None

        url = f"{self.zerion_base_url}/wallets/{address}/transactions/?currency=usd&page[size]=100&filter[operation_types]={operation_type}&filter[trash]=only_non_trash"
        
        headers = {
            "accept": "application/json",
            "authorization": self.zerion_api_key
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            while url:
                try:
                    async with session.get(url) as response:
                        response.raise_for_status()
                        data = await response.json()
                        
                        if 'data' in data:
                            all_transactions.extend(data['data'])
                        
                        url = data.get('links', {}).get('next')

                except aiohttp.ClientError as e:
                    print(f"Error fetching data: {e}")
                    return None
                except json.JSONDecodeError:
                    print("Error decoding JSON response.")
                    return None
                
        return all_transactions
