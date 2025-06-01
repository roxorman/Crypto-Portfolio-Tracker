# standalone_alert_tester.py
# This script is designed for testing the core logic of token price alert checking
# independently of the main application. It uses mock data for alerts and fetches
# live prices from the Mobula API.

import asyncio
import logging
from typing import List, Dict, Any, Optional # Removed Tuple as it wasn't used
import datetime # For timestamping alerts and logging
import time     # For sleep and performance timing
import json     # For pretty-printing JSON data (primarily for debugging)
import sys      # For sys.exit() on critical errors

# Assuming api_fetcher.py and config.py are in the same directory or accessible in PYTHONPATH
from api_fetcher import PortfolioFetcher # Handles API interactions
from config import Config                # Manages configuration like API keys
from notifier import Notifier            # Handles sending notifications
from telegram.helpers import escape_markdown # For MarkdownV2 formatting

# --- Logging Configuration ---
# Configure logging to provide insights into the script's operation.
# Logs to both console and a file for easier debugging.
# Explicitly set UTF-8 encoding for the file handler to prevent UnicodeEncodeError.
logger = logging.getLogger("AlertTester")
logger.setLevel(logging.INFO) # Set level for the logger itself

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Console Handler
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

# File Handler
# Use 'w' mode to overwrite the log file on each run for cleaner test logs,
# or 'a' to append.
file_handler = logging.FileHandler("alert_tester.log", mode='w', encoding='utf-8')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Prevent basicConfig from being called implicitly by other loggers if they get initialized
# logging.basicConfig(level=logging.INFO, handlers=[]) # This line might be redundant if no other module calls basicConfig
logger.info("=== ALERT TESTER INITIALIZING ===")

# --- Mock Data Structures ---
# These simulate data that would typically be retrieved from a database
# or through user interactions in the main application.

# MockAlert: Defines the structure for a single alert.
MockAlert = Dict[str, Any]

# mock_db_alerts: A list of predefined alerts for testing purposes.
# Each dictionary represents an alert with its properties.
mock_db_alerts: List[MockAlert] = [
    {"alert_id": 1, "user_id": 5835173900, "token_mobula_id": 100010811, "token_display_name": "Solana (SOL)", "condition": "above", "target_price": 180.00, "label": "SOL high", "is_active": True, "last_triggered_price": None},
    {"alert_id": 2, "user_id": 5835173900, "token_mobula_id": 100010811, "token_display_name": "Solana (SOL)", "condition": "below", "target_price": 150.00, "label": "SOL low", "is_active": True, "last_triggered_price": None},
    {"alert_id": 3, "user_id": 5835173900, "token_mobula_id": 102480728, "token_display_name": "Popcat (POPCAT)", "condition": "above", "target_price": 0.60, "label": "POPCAT moon", "is_active": True, "last_triggered_price": None},
    {"alert_id": 4, "user_id": 5835173900, "token_mobula_id": 100010811, "token_display_name": "Solana (SOL)", "condition": "above", "target_price": 162.00, "label": "SOL watch", "is_active": True, "last_triggered_price": None},
    {"alert_id": 5, "user_id": 5835173900, "token_mobula_id": 100012309, "token_display_name": "USDC", "condition": "below", "target_price": 0.99, "label": "USDC depeg", "is_active": False, "last_triggered_price": None}, # Example of an inactive alert
    {"alert_id": 6, "user_id": 5835173900, "token_mobula_id": 100001656, "token_display_name": "Bitcoin (BTC)", "condition": "above", "target_price": 70000.00, "label": "BTC ATH", "is_active": True, "last_triggered_price": None},
]
logger.info(f"Loaded {len(mock_db_alerts)} mock alerts for testing.")
# logger.debug(f"Mock alerts data: {json.dumps(mock_db_alerts, indent=2)}") # Uncomment for detailed view of mock data

# --- Global Price Cache ---
# current_price_cache: Stores token prices fetched during the current polling cycle.
# This avoids redundant API calls for the same token within a single check cycle.
# Key: token_mobula_id (int), Value: price (float)
current_price_cache: Dict[int, float] = {}
logger.debug("Initialized empty global price cache.")


async def fetch_current_prices_for_alerts(
    fetcher: PortfolioFetcher,
    active_alerts: List[MockAlert]
) -> Dict[int, float]:
    """
    Fetches current market prices for all unique tokens present in the list of active alerts.
    It utilizes the Mobula API's /market/multi-data endpoint for efficiency.
    The fetched prices are stored in the global `current_price_cache`.

    Args:
        fetcher: An instance of PortfolioFetcher to make API calls.
        active_alerts: A list of active alert objects.

    Returns:
        A dictionary containing the fetched prices {mobula_id: price}.
        This is also the content of `current_price_cache`.
    """
    logger.info(f"Attempting to fetch prices for {len(active_alerts)} active alerts.")
    start_time = time.time()
    
    global current_price_cache
    current_price_cache.clear() # Ensure cache is fresh for each cycle
    logger.debug("Cleared global price cache for the new fetch cycle.")

    if not active_alerts:
        logger.warning("No active alerts provided; skipping price fetching.")
        return {}

    # Collect unique Mobula IDs from all active alerts to minimize API calls
    unique_mobula_ids_to_fetch = list(set(
        alert["token_mobula_id"] for alert in active_alerts if alert["is_active"] # Double check is_active, though list should be pre-filtered
    ))

    if not unique_mobula_ids_to_fetch:
        logger.warning("No unique Mobula IDs found in active alerts to fetch prices for.")
        return {}

    logger.info(f"Identified {len(unique_mobula_ids_to_fetch)} unique Mobula IDs for price fetching.")
    # logger.debug(f"Unique Mobula IDs: {unique_mobula_ids_to_fetch}") # Uncomment if detailed ID list is needed

    try:
        # Delegate the actual API call to the PortfolioFetcher instance
        fetched_market_data = await fetcher.fetch_mobula_market_multi_data_by_ids(mobula_ids=unique_mobula_ids_to_fetch)
        # logger.debug(f"Raw API response from multi-data: {json.dumps(fetched_market_data, indent=2) if fetched_market_data else 'None'}")
    except Exception as e:
        logger.exception(f"An error occurred during API fetch for multiple tokens: {e}")
        return {} # Return empty if fetch fails

    if fetched_market_data and "dataArray" in fetched_market_data:
        logger.info(f"Successfully received price data for {len(fetched_market_data['dataArray'])} tokens from API.")
        
        for token_data in fetched_market_data["dataArray"]:
            mobula_id = token_data.get("id")
            price = token_data.get("price")
            symbol = token_data.get("symbol", "N/A") # Get symbol for logging
            
            if mobula_id is not None and price is not None:
                try:
                    current_price_cache[int(mobula_id)] = float(price)
                    # logger.debug(f"Cached price for {symbol} (ID: {mobula_id}): ${float(price):,.6f}")
                except ValueError:
                    logger.error(f"Could not parse price for {symbol} (ID: {mobula_id}): '{price}'")
            else:
                logger.warning(f"Missing 'id' or 'price' in token data for symbol '{symbol}': {token_data}")
        
        logger.info(f"Cached prices for {len(current_price_cache)} tokens.")
        # logger.debug(f"Current price cache content: {json.dumps(current_price_cache, indent=2)}")
    else:
        logger.error(f"Failed to fetch market data or response was malformed. Response: {fetched_market_data}")

    elapsed_time = time.time() - start_time
    logger.info(f"Price fetching process completed in {elapsed_time:.2f} seconds.")
    return current_price_cache


async def check_and_trigger_alerts(
    active_alerts: List[MockAlert],
    price_data: Dict[int, float],
    notifier_instance: Notifier
):
    logger.info(f"Checking {len(active_alerts)} active alerts against {len(price_data)} cached prices.")
    start_time = time.time()

    if not price_data:
        logger.warning("No price data available; cannot check alerts.")
        return

    triggered_alerts_info = []
    checked_count = 0
    skipped_due_to_no_price_count = 0

    for alert in active_alerts:
        if not alert.get("is_active", False): # More robust check
            logger.debug(f"Skipping inactive alert ID {alert.get('alert_id', 'N/A')}.")
            continue

        token_id = alert.get("token_mobula_id")
        if token_id is None: # Should not happen if mock data is correct
            logger.error(f"Alert ID {alert.get('alert_id', 'N/A')} is missing 'token_mobula_id'. Skipping.")
            continue
            
        current_price = price_data.get(token_id)

        if current_price is None:
            logger.warning(f"No price found in cache for token {alert.get('token_display_name', 'Unknown')} (ID: {token_id}) "
                           f"needed by alert ID {alert.get('alert_id', 'N/A')}. Skipping this alert.")
            skipped_due_to_no_price_count += 1
            continue

        condition = str(alert.get("condition", "")).lower()
        target_price = alert.get("target_price")

        if target_price is None or not condition: # Ensure essential fields are present
            logger.error(f"Alert ID {alert.get('alert_id', 'N/A')} is missing 'target_price' or 'condition'. Skipping.")
            continue

        alert_triggered_flag = False
        checked_count += 1

        try:
            current_price_float = float(current_price)
            target_price_float = float(target_price)
        except (ValueError, TypeError):
            logger.error(f"Invalid price format for alert ID {alert.get('alert_id', 'N/A')}. "
                           f"Current: '{current_price}', Target: '{target_price}'. Skipping.")
            continue


        if condition == "above" and current_price_float > target_price_float:
            alert_triggered_flag = True
        elif condition == "below" and current_price_float < target_price_float:
            alert_triggered_flag = True

        if alert_triggered_flag:
            # Prepare content for MarkdownV2 message
            # Ensure ALL dynamic string content is escaped.
            label_text = alert.get('label', 'N/A')
            token_display_name_text = alert.get('token_display_name', 'Unknown Token')
            condition_text = condition.capitalize() if condition else 'Unknown Condition'
            
            label_escaped = escape_markdown(str(label_text), version=2)
            token_display_name_escaped = escape_markdown(str(token_display_name_text), version=2)
            condition_text_escaped = escape_markdown(str(condition_text), version=2)

            # Prices within backticks for code block style do not need escaping for '.' or '$'
            # The f-string handles number formatting.
            current_price_md = f"`${current_price_float:,.4f}`"
            target_price_md = f"`${target_price_float:,.2f}`"

            # Construct MarkdownV2 message string
            # Using a list of strings and then joining can be cleaner and easier to debug
            message_lines_md = [
                "🚨 *Price Alert Triggered* 🚨",
                "", # Blank line for spacing
                f"🔔 *Label*: _{label_escaped}_",
                f"🪙 *Token*: *{token_display_name_escaped}*",
                f"📈 *Current Price*: {current_price_md}",
                f"🎯 *Condition*: {condition_text_escaped} {target_price_md}",
                "", # Blank line
                "_This alert may have been automatically deactivated\\._" # Escaped period at the end
            ]
            notification_message_md = "\n".join(message_lines_md)

            # Prepare plain text fallback
            plain_text_message = (
                f"Price Alert Triggered!\n\n"
                f"Label: {label_text}\n"
                f"Token: {token_display_name_text}\n"
                f"Current Price: ${current_price_float:,.4f}\n"
                f"Condition: {condition_text} ${target_price_float:,.2f}\n\n"
                f"This alert may have been automatically deactivated."
            )
            
            logger.info(
                f"ALERT TRIGGERED! User: {alert['user_id']}, AlertID: {alert['alert_id']}, Label: '{label_text}'. "
                f"Attempting MarkdownV2 notification."
            )
            # For thorough debugging of Markdown issues:
            # logger.debug(f"Generated MarkdownV2 Message:\n{notification_message_md}")


            notification_sent_successfully = False
            if notifier_instance and notifier_instance.bot:
                chat_id_to_notify = alert.get('user_id')
                if chat_id_to_notify:
                    if await notifier_instance.send_alert_notification(
                        chat_id=chat_id_to_notify, 
                        message=notification_message_md, 
                        parse_mode="MarkdownV2" # Explicitly use this method's default or override
                    ):
                        logger.info(f"Sent alert notification to user_id: {chat_id_to_notify} using MarkdownV2.")
                        notification_sent_successfully = True
                    else:
                        # The error is logged within send_alert_notification / send_message.
                        # We can add a specific log here too if needed.
                        logger.warning(f"MarkdownV2 sending failed for user {chat_id_to_notify}. Attempting plain text fallback.")
                        if await notifier_instance.send_alert_notification(
                            chat_id=chat_id_to_notify, 
                            message=plain_text_message, 
                            parse_mode=None # Explicitly plain text
                        ):
                            logger.info(f"Successfully sent plain text alert to user_id: {chat_id_to_notify} after MarkdownV2 failed.")
                            notification_sent_successfully = True
                        else:
                            logger.error(f"Also failed to send plain text alert to user_id: {chat_id_to_notify}.")
                else:
                    logger.error(f"Alert ID {alert.get('alert_id', 'N/A')} has no user_id. Cannot send notification.")
            else:
                logger.warning("Notifier not available or not initialized; skipping actual notification sending.")

            # Soft delete: Mark as inactive in the mock data
            alert["is_active"] = False
            alert["last_triggered_price"] = current_price_float
            alert["last_triggered_at"] = datetime.datetime.utcnow().isoformat() # Add timestamp
            logger.info(f"Alert ID {alert.get('alert_id', 'N/A')} for user {alert.get('user_id', 'Unknown')} "
                        f"has been marked as inactive (soft delete).")
            
            triggered_alerts_info.append({
                "user_id": alert.get('user_id'),
                "alert_id": alert.get('alert_id'),
                "token_name": token_display_name_text, # Use unescaped for this internal log
                "label": label_text,
                "condition_met": f"{condition_text} ${target_price_float:,.2f}",
                "current_price": f"${current_price_float:,.4f}",
                "notified_successfully": notification_sent_successfully
            })
    
    if triggered_alerts_info:
        logger.info(f"Successfully processed {len(triggered_alerts_info)} triggered alerts in this cycle.")
    else:
        logger.info("No alerts were triggered during this check cycle (after filtering for price availability).")
    
    elapsed_time = time.time() - start_time
    logger.info(f"Alert checking process completed in {elapsed_time:.2f}s. "
                f"Checked: {checked_count}, Skipped (no price): {skipped_due_to_no_price_count}, Triggered: {len(triggered_alerts_info)}")


async def standalone_alert_polling_loop(fetcher: PortfolioFetcher, notifier_instance: Notifier, polling_interval_seconds: int = 300):
    """
    The main polling loop for the standalone alert tester.
    Periodically fetches active alerts, gets current prices, and checks for triggers.

    Args:
        fetcher: An instance of PortfolioFetcher.
        polling_interval_seconds: The time to wait between alert check cycles.
    """
    logger.info(f"Starting standalone alert polling loop. Check interval: {polling_interval_seconds} seconds.")
    cycle_count = 0
    
    while True:
        cycle_count += 1
        cycle_start_time = time.time()
        logger.info(f"--- Starting Alert Check Cycle #{cycle_count} at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
        
        try:
            # Step 1: Retrieve active alerts.
            # In a real application, this would be a database query:
            # `active_alerts = await db_manager.get_active_token_price_alerts()`
            # For this test script, we filter our mock data.
            current_active_alerts = [alert for alert in mock_db_alerts if alert.get("is_active", False)]
            logger.info(f"Retrieved {len(current_active_alerts)} active alerts from mock data source (total: {len(mock_db_alerts)}).")
            
            if not current_active_alerts:
                logger.info("No active alerts found. Sleeping until next cycle.")
                await asyncio.sleep(polling_interval_seconds)
                continue # Skip to next iteration

            # Step 2: Fetch current prices for tokens in these active alerts.
            # This function populates the global `current_price_cache`.
            await fetch_current_prices_for_alerts(fetcher, current_active_alerts)

            # Step 3: Check alerts against the fetched prices.
            if current_price_cache: # Proceed only if prices were successfully fetched
                await check_and_trigger_alerts(current_active_alerts, current_price_cache, notifier_instance)
            else:
                logger.warning("Price cache is empty after fetch attempt; skipping alert evaluation for this cycle.")

        except Exception as e:
            # Catch-all for unexpected errors within the loop to prevent crashing the poller
            logger.exception(f"An unexpected error occurred in alert polling cycle #{cycle_count}: {e}")

        cycle_duration = time.time() - cycle_start_time
        logger.info(f"--- Alert Check Cycle #{cycle_count} Completed in {cycle_duration:.2f} seconds. ---")
        
        # Wait for the specified interval before starting the next cycle
        logger.info(f"Sleeping for {polling_interval_seconds} seconds...")
        await asyncio.sleep(polling_interval_seconds)


# --- PortfolioFetcher Enhancement for Standalone Testing ---
# The following function is dynamically added to the PortfolioFetcher class for this script.
# This allows testing the multi-data fetch logic without modifying the original api_fetcher.py,
# or if the method doesn't exist there yet.
# In a real scenario, this method should be part of the PortfolioFetcher class itself.
async def fetch_mobula_market_multi_data_by_ids(
    self: PortfolioFetcher, # 'self' to mimic being an instance method
    mobula_ids: List[int]
) -> Optional[Dict[str, Any]]:
    """
    Fetches market data for multiple tokens by their Mobula IDs using the /market/multi-data endpoint.
    This is a helper method, potentially for inclusion in the main PortfolioFetcher class.

    Args:
        self: The PortfolioFetcher instance (contains API key).
        mobula_ids: A list of integer Mobula token IDs.

    Returns:
        A dictionary containing the API response, or None if an error occurs.
        The useful data is typically under the "dataArray" key.
    """
    if not self.api_key: # Ensure API key is available from Config via PortfolioFetcher
        logger.error("MOBULA_API_KEY is not configured in PortfolioFetcher. Cannot fetch prices.")
        return None
    if not mobula_ids:
        logger.warning("fetch_mobula_market_multi_data_by_ids called with an empty list of IDs.")
        return None

    # Mobula API endpoint for fetching multiple token data
    url = "https://api.mobula.io/api/1/market/multi-data"
    # Convert list of IDs to a comma-separated string as required by the API
    ids_param_str = ",".join(map(str, mobula_ids))
    
    params = {"ids": ids_param_str}
    # logger.debug(f"Constructed API request params: {params}")

    # Standard headers, including Authorization with the API key
    request_headers = {
        "Authorization": self.api_key, # Send the full API key
        "User-Agent": "CryptoAlertBotStandaloneTester/1.0" # Identify the client
    }
    logger.info(f"Fetching multi-data from Mobula for {len(mobula_ids)} token IDs.")
    # logger.debug(f"Requesting URL: {url} with IDs: {ids_param_str[:50]}...") # Log partial IDs if too long

    try:
        # This part assumes PortfolioFetcher uses aiohttp or a similar async HTTP client.
        # For this standalone script, we'll instantiate aiohttp directly.
        import aiohttp # Required for async HTTP requests
        
        async with aiohttp.ClientSession(headers=request_headers, timeout=aiohttp.ClientTimeout(total=30)) as session:
            request_start_time = time.time()
            async with session.get(url, params=params) as response:
                response_time = time.time() - request_start_time
                logger.debug(f"API request to {response.url} completed with status {response.status} in {response_time:.2f}s.")
                
                response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
                raw_data = await response.json()
                # logger.debug(f"Received API response (size: {len(str(raw_data))} chars).")
        
        # Validate the structure of the response
        if isinstance(raw_data, dict) and "dataArray" in raw_data:
            num_items_received = len(raw_data.get('dataArray', []))
            logger.info(f"Successfully fetched multi-data for {num_items_received} items from Mobula.")
            # if num_items_received > 0:
            #     logger.debug(f"Sample token from response: {raw_data['dataArray'][0].get('symbol', 'N/A')}")
            return raw_data # Return the full response dictionary
        else:
            logger.error(f"Unexpected Mobula API response structure for multi-data. Data: {str(raw_data)[:200]}...")
            return None

    except aiohttp.ClientResponseError as e: # Specific HTTP error from aiohttp
        logger.error(f"HTTP error {e.status} fetching Mobula multi-data: {e.message}. URL: {e.request_info.url if e.request_info else url}")
        return None
    except aiohttp.ClientError as e: # General aiohttp client error (e.g., connection issues)
        logger.error(f"AIOHTTP client error fetching Mobula multi-data: {e}")
        return None
    except asyncio.TimeoutError: # Timeout during the request
        logger.error(f"Request to Mobula multi-data timed out. URL: {url}, Params: {params}")
        return None
    except json.JSONDecodeError as e: # Error parsing JSON response
        logger.error(f"Failed to decode JSON response from Mobula multi-data: {e}. Response text might not be valid JSON.")
        return None
    except Exception as e: # Catch any other unexpected errors
        logger.exception(f"An unexpected error occurred while fetching Mobula multi-data: {e}")
        return None

# Dynamically attach the method to PortfolioFetcher class for use within this script.
# This is a workaround for testing; ideally, this method would be part of the main PortfolioFetcher class.
PortfolioFetcher.fetch_mobula_market_multi_data_by_ids = fetch_mobula_market_multi_data_by_ids
logger.debug("Dynamically attached 'fetch_mobula_market_multi_data_by_ids' to PortfolioFetcher for this script.")


# --- Main Execution Block ---
if __name__ == "__main__":
    logger.info("--- STANDALONE ALERT TESTER SCRIPT STARTED ---")
    
    try:
        # Load configuration (primarily for the API key)
        logger.info("Loading configuration from config.py...")
        cfg = Config()
        if not cfg.MOBULA_API_KEY:
            logger.critical("MOBULA_API_KEY is not found in the configuration. This script cannot run without it. Please check your .env file or environment variables.")
            sys.exit(1) # Exit if API key is missing
        logger.info(f"MOBULA_API_KEY loaded successfully (partial: {cfg.MOBULA_API_KEY[:5]}...).")
        
        # Instantiate PortfolioFetcher
        logger.info("Creating PortfolioFetcher instance...")
        portfolio_fetcher_instance = PortfolioFetcher()

        # Instantiate Notifier
        logger.info("Creating Notifier instance...")
        notifier_instance = Notifier()
        if not notifier_instance.bot:
            logger.warning("Telegram Bot could not be initialized in Notifier. Notifications will not be sent.")

        # Define the polling interval
        test_polling_interval_seconds = 60
        logger.info(f"Alert polling interval set to {test_polling_interval_seconds} seconds.")

        # Start the asynchronous polling loop
        logger.info("Starting the asynchronous alert polling loop...")
        asyncio.run(standalone_alert_polling_loop(portfolio_fetcher_instance, notifier_instance, test_polling_interval_seconds))

    except KeyboardInterrupt:
        # Allow graceful shutdown
        logger.info("KeyboardInterrupt received. Shutting down the alert tester...")
    except Exception as main_exc:
        # Catch any other critical errors in the main execution flow
        logger.exception(f"A critical error occurred in the main execution block: {main_exc}")
    finally:
        logger.info("--- STANDALONE ALERT TESTER SCRIPT FINISHED ---")
