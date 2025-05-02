from typing import Dict, List, Optional
from models import Alert, Portfolio, Wallet
from api_fetcher import PortfolioFetcher
from notifier import Notifier
from db_manager import DatabaseManager
import asyncio
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class AlertsManager:
    """Manages alert checking and notifications for portfolios and tokens."""
    
    def __init__(self, db_manager: DatabaseManager, notifier: Notifier, portfolio_fetcher: PortfolioFetcher):
        self.db = db_manager # <<< STORE the db_manager instance
        self.notifier = notifier # <<< STORE the notifier instance
        self.portfolio_fetcher = portfolio_fetcher # <<< STORE the portfolio_fetcher instance
        self.check_interval = 60  # Check alerts every 60 seconds
        logger.info("AlertsManager initialized.")

    async def create_portfolio_alert(self, user_id: int, portfolio_id: int,
                                   target_value: float, condition: str) -> Alert:
        """Create a new portfolio value alert."""
        conditions = {
            'type': 'portfolio_value',
            'target_value': target_value,
            'condition': condition  # 'above' or 'below'
        }
        return await self.db.create_alert(
            user_id=user_id,
            alert_type='portfolio_value',
            conditions=conditions,
            portfolio_id=portfolio_id
        )

    async def create_token_alert(self, user_id: int, token_address: str,
                               target_price: float, condition: str,
                               chain: str = 'ethereum') -> Alert:
        """Create a new token price alert."""
        conditions = {
            'type': 'token_price',
            'token_address': token_address,
            'chain': chain,
            'target_price': target_price,
            'condition': condition  # 'above' or 'below'
        }
        return await self.db.create_alert(
            user_id=user_id,
            alert_type='token_price',
            conditions=conditions
        )

    async def create_wallet_alert(self, user_id: int, wallet_id: int,
                                target_value: float, condition: str) -> Alert:
        """Create a new wallet value alert."""
        conditions = {
            'type': 'wallet_value',
            'target_value': target_value,
            'condition': condition  # 'above' or 'below'
        }
        return await self.db.create_alert(
            user_id=user_id,
            alert_type='wallet_value',
            conditions=conditions,
            wallet_id=wallet_id
        )

    async def check_portfolio_alert(self, alert: Alert, portfolio: Portfolio) -> bool:
        """Check if a portfolio alert has been triggered."""
        holdings = await self.portfolio_fetcher.get_portfolio_holdings(portfolio)
        if not holdings:
            return False

        current_value = holdings['total_value']
        target_value = alert.conditions['target_value']
        condition = alert.conditions['condition']

        return (
            (condition == 'above' and current_value >= target_value) or
            (condition == 'below' and current_value <= target_value)
        )

    async def check_wallet_alert(self, alert: Alert, wallet: Wallet) -> bool:
        """Check if a wallet alert has been triggered."""
        holdings = await self.portfolio_fetcher.get_wallet_holdings(wallet)
        if not holdings:
            return False

        current_value = holdings['total_value']
        target_value = alert.conditions['target_value']
        condition = alert.conditions['condition']

        return (
            (condition == 'above' and current_value >= target_value) or
            (condition == 'below' and current_value <= target_value)
        )

    async def check_token_alert(self, alert: Alert) -> bool:
        """Check if a token price alert has been triggered."""
        try:
            token_address = alert.conditions['token_address']
            chain = alert.conditions['chain']
            target_price = alert.conditions['target_price']
            condition = alert.conditions['condition']

            # Get current token price from Mobula API
            current_price = await self.get_token_price(token_address, chain)
            if not current_price:
                return False

            return (
                (condition == 'above' and current_price >= target_price) or
                (condition == 'below' and current_price <= target_price)
            )
        except Exception as e:
            print(f"Error checking token alert: {e}")
            return False

    async def get_token_price(self, token_address: str, chain: str) -> Optional[float]:
        """Get current token price from Mobula API."""
        try:
            url = f"{self.portfolio_fetcher.base_url}/tokens/prices"
            params = {
                "addresses": token_address,
                "blockchain": chain
            }
            headers = {"Authorization": self.portfolio_fetcher.api_key}

            response = requests.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

            if data and isinstance(data, dict) and data.get('data'):
                return float(data['data'][0]['price'])
            return None
        except Exception as e:
            print(f"Error fetching token price: {e}")
            return None

    async def format_alert_message(self, alert: Alert, triggered_value: float) -> str:
        """Format alert notification message."""
        alert_type = alert.conditions['type']
        condition = alert.conditions['condition']
        target_value = alert.conditions['target_value']

        if alert_type == 'portfolio_value':
            return (
                "🚨 Portfolio Alert!\n"
                f"Portfolio value is now ${triggered_value:,.2f}\n"
                f"Target was {condition} ${target_value:,.2f}"
            )
        elif alert_type == 'wallet_value':
            return (
                "🚨 Wallet Alert!\n"
                f"Wallet value is now ${triggered_value:,.2f}\n"
                f"Target was {condition} ${target_value:,.2f}"
            )
        elif alert_type == 'token_price':
            return (
                "🚨 Price Alert!\n"
                f"Token price is now ${triggered_value:,.4f}\n"
                f"Target was {condition} ${target_value:,.4f}"
            )

    async def check_all_alerts(self):
        """Check all active alerts."""
        while True:
            try:
                # Get all active alerts from database
                alerts = await self.db.get_active_alerts()
                
                for alert in alerts:
                    triggered = False
                    triggered_value = 0

                    if alert.conditions['type'] == 'portfolio_value' and alert.portfolio_id:
                        portfolio = await self.db.get_portfolio(alert.portfolio_id)
                        triggered = await self.check_portfolio_alert(alert, portfolio)
                        if triggered:
                            holdings = await self.portfolio_fetcher.get_portfolio_holdings(portfolio)
                            triggered_value = holdings['total_value']

                    elif alert.conditions['type'] == 'wallet_value' and alert.wallet_id:
                        wallet = await self.db.get_wallet(alert.wallet_id)
                        triggered = await self.check_wallet_alert(alert, wallet)
                        if triggered:
                            holdings = await self.portfolio_fetcher.get_wallet_holdings(wallet)
                            triggered_value = holdings['total_value']

                    elif alert.conditions['type'] == 'token_price':
                        triggered = await self.check_token_alert(alert)
                        if triggered:
                            triggered_value = await self.get_token_price(
                                alert.conditions['token_address'],
                                alert.conditions['chain']
                            )

                    if triggered:
                        # Format and send notification
                        message = await self.format_alert_message(alert, triggered_value)
                        await self.notifier.send_alert_notification(alert.user_id, message)
                        
                        # Deactivate one-time alerts
                        if not alert.conditions.get('recurring', False):
                            await self.db.deactivate_alert(alert.alert_id)

            except Exception as e:
                print(f"Error checking alerts: {e}")

            await asyncio.sleep(self.check_interval)
