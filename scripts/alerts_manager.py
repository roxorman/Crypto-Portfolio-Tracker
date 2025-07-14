import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone

from sqlalchemy.future import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.helpers import escape_markdown

# Assuming these modules and classes will exist or be adjusted
from db_manager import DatabaseManager
from notifier import Notifier
from api_fetcher import PortfolioFetcher
from models import Alert
from alert_handlers import CALLBACK_REACTIVATE_ALERT_PREFIX, CALLBACK_DEACTIVATE_ALERT_PREFIX
from utils import format_price_dynamically # Added import

logger = logging.getLogger(__name__)

class AlertsManager:
    def __init__(
        self,
        db_manager: DatabaseManager,
        notifier: Notifier,
        portfolio_fetcher: PortfolioFetcher,
        check_interval_seconds: int = 270  # Default check interval 1 minute
    ):
        self.db = db_manager
        self.notifier = notifier
        self.portfolio_fetcher = portfolio_fetcher
        self._current_price_cache: Dict[int, float] = {} # {token_mobula_id: price}
        self.check_interval_seconds = check_interval_seconds
        self._is_running = False
        logger.info(f"AlertsManager initialized with check interval: {check_interval_seconds}s")

    async def _fetch_and_cache_cmc_prices(self) -> bool:
        """Fetches and caches prices for active CMC alerts."""
        self._current_price_cache.clear()
        active_alerts = await self.db.get_active_token_price_alerts()
        if not active_alerts:
            logger.info("No active CMC token price alerts found.")
            return False

        unique_cmc_ids = list(set(alert.cmc_id for alert in active_alerts if alert.cmc_id is not None))
        if not unique_cmc_ids:
            return False

        logger.info(f"Fetching CMC prices for {len(unique_cmc_ids)} unique IDs.")
        api_data_map = await self.portfolio_fetcher.fetch_cmc_token_quotes(ids=unique_cmc_ids)
        if not api_data_map:
            logger.error("Failed to fetch market data from CMC API.")
            return False

        for cmc_id_str, token_data_obj in api_data_map.items():
            token_entry = token_data_obj[0] if isinstance(token_data_obj, list) and token_data_obj else token_data_obj
            if isinstance(token_entry, dict):
                price = token_entry.get("quote", {}).get("USD", {}).get("price")
                actual_cmc_id = token_entry.get("id")
                if price is not None and actual_cmc_id is not None:
                    self._current_price_cache[int(actual_cmc_id)] = float(price)
        
        if self._current_price_cache:
            logger.info(f"Successfully cached prices from CMC for {len(self._current_price_cache)} tokens.")
            return True
        return False

    async def _evaluate_and_notify_cmc_alerts(self):
        """Evaluates active CMC alerts against cached prices."""
        if not self._current_price_cache:
            logger.warning("CMC price cache is empty. Skipping evaluation.")
            return

        active_alerts = await self.db.get_active_token_price_alerts()
        if not active_alerts:
            return

        logger.info(f"Evaluating {len(active_alerts)} active CMC alerts.")
        for alert in active_alerts:
            current_price = self._current_price_cache.get(alert.cmc_id)
            if current_price is not None:
                await self._check_and_trigger_alert(alert, current_price)

    async def _evaluate_and_notify_coingecko_alerts(self, alerts: List[Alert], price_data: Dict[str, Any]):
        """Evaluates a list of CoinGecko alerts against fetched price data."""
        logger.info(f"Evaluating {len(alerts)} CoinGecko alerts.")
        # Create a case-insensitive mapping of the price data for safe lookups
        price_data_lower = {k.lower(): v for k, v in price_data.items()}

        for alert in alerts:
            # Perform a case-insensitive lookup
            price_info = price_data_lower.get(alert.token_address.lower())
            if price_info is not None:
                try:
                    current_price = float(price_info)
                    await self._check_and_trigger_alert(alert, current_price)
                except (ValueError, TypeError):
                    logger.warning(f"Could not parse price for CoinGecko alert {alert.alert_id} (Address: {alert.token_address}). Price: {price_info}")
            else:
                logger.warning(f"No price found for CoinGecko alert {alert.alert_id} (Address: {alert.token_address})")

    async def _check_and_trigger_alert(self, alert: Alert, current_price: float):
        """Checks if an alert's conditions are met and triggers notification if so."""
        conditions = alert.conditions
        target_price = float(conditions.get("target_price", 0))
        condition_type = conditions.get("condition", "").lower()

        alert_triggered = False
        if condition_type == "above" and current_price > target_price:
            alert_triggered = True
        elif condition_type == "below" and current_price < target_price:
            alert_triggered = True

        if alert_triggered:
            logger.info(f"Alert TRIGGERED: ID {alert.alert_id}, User {alert.user_id}, Token {alert.token_display_name}, Price {current_price}")
            await self._send_alert_notification(alert, current_price)
            await self.db.deactivate_alert_and_log_trigger(alert.alert_id, current_price)

    async def _send_alert_notification(self, alert: Alert, current_price: float):
        """Constructs and sends the alert notification message."""
        label = alert.conditions.get("label", "N/A")
        condition_type = alert.conditions.get("condition", "N/A")
        target_price = float(alert.conditions.get("target_price", 0))

        label_escaped = escape_markdown(label, version=2)
        token_display_name_escaped = escape_markdown(alert.token_display_name or "Unknown Token", version=2)
        condition_type_escaped = escape_markdown(condition_type.capitalize(), version=2)
        current_price_str = f"${format_price_dynamically(current_price)}"
        target_price_str = f"${format_price_dynamically(target_price)}"

        notification_message = (
            f"🚨 *Price Alert Triggered* 🚨\n\n"
            f"🔔 *Label*: _{label_escaped}_\n"
            f"🪙 *Token*: *{token_display_name_escaped}*\n"
            f"📈 *Current Price*: `{escape_markdown(current_price_str, version=2)}`\n"
            f"🎯 *Condition*: {condition_type_escaped} `{escape_markdown(target_price_str, version=2)}`\n\n"
            f"This alert has now been deactivated\\."
        )
        keyboard = [[
            InlineKeyboardButton("🔄 Reactivate", callback_data=f"{CALLBACK_REACTIVATE_ALERT_PREFIX}{alert.alert_id}"),
            InlineKeyboardButton("✅ OK", callback_data=f"{CALLBACK_DEACTIVATE_ALERT_PREFIX}{alert.alert_id}")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await self.notifier.send_alert_notification(
            chat_id=alert.user_id,
            message=notification_message,
            reply_markup=reply_markup,
            parse_mode="MarkdownV2"
        )


    async def check_cmc_alerts_loop(self):
        """Main polling loop for CoinMarketCap-based alerts."""
        self._is_running = True
        logger.info("CMC AlertsManager polling loop started.")
        while self._is_running:
            try:
                prices_fetched = await self._fetch_and_cache_cmc_prices()
                if prices_fetched:
                    await self._evaluate_and_notify_cmc_alerts()
            except Exception as e:
                logger.exception(f"Critical error in CMC alert checking cycle: {e}")
            
            logger.info(f"CMC alert cycle finished. Sleeping for {self.check_interval_seconds}s.")
            await asyncio.sleep(self.check_interval_seconds)
        logger.info("CMC AlertsManager polling loop stopped.")

    async def check_coingecko_alerts_loop(self):
        """Main polling loop for CoinGecko-based alerts."""
        self._is_running = True
        logger.info("CoinGecko AlertsManager polling loop started.")
        # Define a fixed check interval for the entire loop.
        check_interval = 270  # seconds

        while self._is_running:
            try:
                active_alerts = await self.db.get_active_coingecko_token_price_alerts()
                if not active_alerts:
                    logger.info(f"No active CoinGecko alerts. Sleeping for {check_interval}s.")
                    await asyncio.sleep(check_interval)
                    continue

                # Create concurrent tasks to fetch details for all active alerts
                tasks = []
                for alert in active_alerts:
                    tasks.append(
                        self.portfolio_fetcher.fetch_coingecko_token_details(
                            network_id=alert.network_id,
                            token_address=alert.token_address
                        )
                    )
                
                logger.info(f"Concurrently fetching details for {len(tasks)} CoinGecko alerts.")
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Now, evaluate all alerts with the fetched results
                for alert, result in zip(active_alerts, results):
                    if isinstance(result, Exception):
                        logger.error(f"Error fetching details for alert {alert.alert_id}: {result}")
                        continue

                    if result and result.get("price_usd") is not None:
                        current_price = result["price_usd"]
                        await self._check_and_trigger_alert(alert, current_price)
                    else:
                        logger.warning(f"Failed to fetch price for alert {alert.alert_id} (Address: {alert.token_address})")

            except Exception as e:
                logger.exception(f"Critical error in CoinGecko alert checking cycle: {e}")
            
            logger.info(f"CoinGecko alert cycle finished. Sleeping for {check_interval}s.")
            await asyncio.sleep(check_interval)
        
        logger.info("CoinGecko AlertsManager polling loop stopped.")

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
