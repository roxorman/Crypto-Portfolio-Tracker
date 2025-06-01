import asyncio
import logging
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from sqlalchemy.future import select
from telegram.helpers import escape_markdown

# Assuming these modules and classes will exist or be adjusted
from db_manager import DatabaseManager
from notifier import Notifier
from api_fetcher import PortfolioFetcher
from models import Alert
from utils import format_price_dynamically # Added import

logger = logging.getLogger(__name__)

class AlertsManager:
    def __init__(
        self,
        db_manager: DatabaseManager,
        notifier: Notifier,
        portfolio_fetcher: PortfolioFetcher,
        check_interval_seconds: int = 60  # Default check interval 1 minute
    ):
        self.db = db_manager
        self.notifier = notifier
        self.portfolio_fetcher = portfolio_fetcher
        self._current_price_cache: Dict[int, float] = {} # {token_mobula_id: price}
        self.check_interval_seconds = check_interval_seconds
        self._is_running = False
        logger.info(f"AlertsManager initialized with check interval: {check_interval_seconds}s")

    async def _fetch_and_cache_prices_for_active_alerts(self) -> bool:
        """
        Fetches current prices for all unique tokens in active 'token_price' alerts
        and populates the internal price cache.
        """
        self._current_price_cache.clear()
        logger.info("Fetching active token price alerts for price caching.")
        active_alerts: List[Alert] = await self.db.get_active_token_price_alerts()

        if not active_alerts:
            logger.info("No active token price alerts found to fetch prices for.")
            return False

        unique_cmc_ids = list(set(
            alert.cmc_id for alert in active_alerts if alert.cmc_id is not None
        ))

        if not unique_cmc_ids:
            logger.info("No unique CMC IDs found in active token price alerts.")
            return False

        logger.info(f"Fetching prices for {len(unique_cmc_ids)} unique CMC IDs: {unique_cmc_ids}")
        
        try:
            # fetch_cmc_token_quotes returns the 'data' part of the CMC API response
            # This 'data' is a dictionary where keys are stringified CMC IDs (or symbols/slugs if used for query)
            # and values are token data objects.
            api_data_map = await self.portfolio_fetcher.fetch_cmc_token_quotes(ids=unique_cmc_ids)
            
            if api_data_map:
                for cmc_id_str, token_data_obj in api_data_map.items():
                    # If queried by ID, CMC might return a single object directly, not a list.
                    # If queried by symbol/slug, it returns a list.
                    # Since we query by ID list here, each key (cmc_id_str) should map to a single token object.
                    
                    token_entry = None
                    if isinstance(token_data_obj, list) and token_data_obj:
                        token_entry = token_data_obj[0] # Take the first if it's a list (should not happen if queried by ID)
                    elif isinstance(token_data_obj, dict):
                        token_entry = token_data_obj

                    if token_entry:
                        price_quote = token_entry.get("quote", {}).get("USD", {})
                        price = price_quote.get("price")
                        actual_cmc_id = token_entry.get("id") # Use the ID from the response data for consistency

                        if actual_cmc_id is not None and price is not None:
                            try:
                                self._current_price_cache[int(actual_cmc_id)] = float(price)
                            except ValueError:
                                logger.error(f"Could not parse price for CMC ID {actual_cmc_id}: {price}")
                        else:
                            logger.warning(f"Missing id or price in token data from CMC API for queried ID {cmc_id_str}: {token_entry}")
                    else:
                        logger.warning(f"No token data found in CMC response for queried ID {cmc_id_str}")
                
                if self._current_price_cache:
                    logger.info(f"Successfully cached prices from CMC for {len(self._current_price_cache)} tokens.")
                    return True
                else:
                    logger.warning("Price cache is empty after processing API response.")
                    return False
            else:
                logger.error(f"Failed to fetch or parse market multi-data. API Response: {str(api_response)[:500]}")
                return False
        except Exception as e:
            logger.exception(f"Error during price fetching and caching: {e}")
            return False

    async def _evaluate_and_notify_token_alerts(self):
        """
        Evaluates active token price alerts against cached prices and sends notifications if triggered.
        """
        if not self._current_price_cache:
            logger.warning("Price cache is empty. Skipping token alert evaluation.")
            return

        active_alerts: List[Alert] = await self.db.get_active_token_price_alerts()
        if not active_alerts:
            logger.info("No active token price alerts to evaluate.")
            return

        logger.info(f"Evaluating {len(active_alerts)} active token price alerts against {len(self._current_price_cache)} cached prices.")
        triggered_count = 0

        for alert in active_alerts:
            if not alert.is_active or alert.alert_type != 'token_price' or alert.cmc_id is None: # Use cmc_id
                continue 

            current_price = self._current_price_cache.get(alert.cmc_id) # Use cmc_id
            if current_price is None:
                logger.warning(f"No cached price found for CMC ID {alert.cmc_id} (Alert ID: {alert.alert_id}). Skipping.")
                continue

            conditions = alert.conditions
            target_price = conditions.get("target_price")
            condition_type = conditions.get("condition", "").lower()
            label = conditions.get("label", "N/A")

            if target_price is None or not condition_type:
                logger.error(f"Alert ID {alert.alert_id} has invalid conditions: {conditions}. Skipping.")
                continue
            
            try:
                target_price = float(target_price)
            except ValueError:
                logger.error(f"Alert ID {alert.alert_id} has non-float target_price: {target_price}. Skipping.")
                continue

            alert_triggered = False
            if condition_type == "above" and current_price > target_price:
                alert_triggered = True
            elif condition_type == "below" and current_price < target_price:
                alert_triggered = True

            if alert_triggered:
                logger.info(f"Token Price Alert TRIGGERED: Alert ID {alert.alert_id} for User {alert.user_id}. Token: {alert.token_display_name}, Condition: {condition_type} {target_price}, Current Price: {current_price}")
                triggered_count += 1

                # Construct MarkdownV2 message
                label_escaped = escape_markdown(label, version=2)
                token_display_name_escaped = escape_markdown(alert.token_display_name or "Unknown Token", version=2)
                condition_type_escaped = escape_markdown(condition_type.capitalize(), version=2)

                current_price_str = f"${format_price_dynamically(current_price)}"
                target_price_str = f"${format_price_dynamically(target_price)}" # Using .2f for target as it's user-defined

                # The final sentence needs its period escaped for MarkdownV2.
                final_message_part = "This alert has now been deactivated\." # Escaped period

                notification_message = (
                    f"🚨 *Price Alert Triggered* 🚨\n\n"
                    f"🔔 *Label*: _{label_escaped}_\n"
                    f"🪙 *Token*: *{token_display_name_escaped}*\n"
                    f"📈 *Current Price*: `{current_price_str}`\n"
                    f"🎯 *Condition*: {condition_type_escaped} `{target_price_str}`\n\n"
                    f"{final_message_part}"
                )
                
                send_success = await self.notifier.send_alert_notification(
                    chat_id=alert.user_id, 
                    message=notification_message, 
                    parse_mode="MarkdownV2"
                )

                if not send_success:
                    logger.error(f"Failed to send MarkdownV2 alert for Alert ID {alert.alert_id}. Attempting plain text.")
                    plain_text_message = (
                        f"Price Alert Triggered!\n\n"
                        f"Label: {label}\n"
                        f"Token: {alert.token_display_name or 'Unknown Token'}\n"
                        f"Current Price: ${format_price_dynamically(current_price)}\n"
                        f"Condition: {condition_type.capitalize()} ${format_price_dynamically(target_price)}\n\n"
                        f"This alert has now been deactivated."
                    )
                    send_success = await self.notifier.send_alert_notification(
                        chat_id=alert.user_id,
                        message=plain_text_message,
                        parse_mode=None
                    )
                
                if send_success:
                    logger.info(f"Successfully sent notification for Alert ID {alert.alert_id} to User {alert.user_id}.")
                else:
                    logger.error(f"Failed to send notification for Alert ID {alert.alert_id} to User {alert.user_id} after fallback.")
                
                # Deactivate alert in DB
                deactivated = await self.db.deactivate_alert_and_log_trigger(
                    alert_id=alert.alert_id, 
                    triggered_price=current_price
                )
                if not deactivated:
                    logger.error(f"Failed to deactivate Alert ID {alert.alert_id} in database.")
        
        if triggered_count > 0:
            logger.info(f"Finished evaluating token alerts. Triggered {triggered_count} alerts in this cycle.")
        else:
            logger.info("Finished evaluating token alerts. No alerts triggered in this cycle.")


    async def check_all_alerts_loop(self):
        """
        Main loop that periodically fetches prices and evaluates all types of alerts.
        """
        self._is_running = True
        logger.info("AlertsManager polling loop started.")
        
        while self._is_running:
            cycle_start_time = time.monotonic()
            logger.info(f"--- Starting new alert check cycle at {datetime.now(timezone.utc)} ---")

            try:
                # --- Token Price Alerts ---
                prices_fetched = await self._fetch_and_cache_prices_for_active_alerts()
                if prices_fetched:
                    await self._evaluate_and_notify_token_alerts()
                else:
                    logger.info("Skipping token alert evaluation as no prices were fetched/cached.")

                # --- Placeholder for other alert types ---
                # Example: await self._evaluate_portfolio_value_alerts()
                # Example: await self._evaluate_transaction_alerts()
                
                logger.info("All alert types processed for this cycle.")

            except Exception as e:
                logger.exception(f"Critical error in alert checking cycle: {e}")
                # Avoid rapid-fire loops on persistent errors; add a longer sleep
                await asyncio.sleep(self.check_interval_seconds * 2) 

            cycle_duration = time.monotonic() - cycle_start_time
            logger.info(f"--- Alert check cycle completed in {cycle_duration:.2f} seconds ---")
            
            sleep_duration = self.check_interval_seconds - cycle_duration
            if sleep_duration > 0:
                logger.info(f"Sleeping for {sleep_duration:.2f} seconds until next cycle.")
                await asyncio.sleep(sleep_duration)
            else:
                logger.warning(f"Alert cycle duration ({cycle_duration:.2f}s) exceeded check interval ({self.check_interval_seconds}s). Starting next cycle immediately.")
                await asyncio.sleep(1) # Brief sleep to prevent tight loop if consistently overrunning

        logger.info("AlertsManager polling loop stopped.")

    def stop_loop(self):
        """Signals the polling loop to stop."""
        logger.info("Stop signal received for AlertsManager loop.")
        self._is_running = False

# Example of how it might be run (e.g., in main.py)
# async def main():
#     # Initialize db_manager, notifier, portfolio_fetcher
#     # ...
#     alerts_mgr = AlertsManager(db_manager, notifier, portfolio_fetcher, check_interval_seconds=60)
#     try:
#         await alerts_mgr.check_all_alerts_loop()
#     except KeyboardInterrupt:
#         logger.info("Alerts manager loop interrupted by user.")
#     finally:
#         alerts_mgr.stop_loop() # Ensure loop can exit if it's still running
#         # Perform any other cleanup
#
# if __name__ == '__main__':
#     # Setup basic logging for standalone testing if needed
#     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
#     # asyncio.run(main())
