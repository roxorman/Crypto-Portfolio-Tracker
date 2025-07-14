import asyncio
from typing import Dict, List
from datetime import datetime, timedelta
from db_manager import DatabaseManager
from api_fetcher import PortfolioFetcher
from alerts_manager import AlertsManager
from notifier import Notifier

from db_manager import DatabaseManager
from api_fetcher import PortfolioFetcher
from alerts_manager import AlertsManager
from notifier import Notifier

import logging

logger = logging.getLogger(__name__)

class Scheduler:
    """Handles scheduled tasks like portfolio updates and alert checking."""

    def __init__(self, db_manager: DatabaseManager, notifier: Notifier, portfolio_fetcher: PortfolioFetcher = None, alerts_manager: AlertsManager = None):
        self.db = db_manager
        self.portfolio_fetcher = portfolio_fetcher
        self.alerts_manager = alerts_manager
        self.notifier = notifier
        self.running_tasks = {}

        # Default intervals (in seconds)
        self.update_interval = 3600  # Update portfolios every hour
        self.alert_interval = 60     # Check alerts every minute
        self.snapshot_interval = 86400  # Take daily snapshots
        self.premium_check_interval = 3600 # Check for expired premiums every hour

    async def start(self):
        """Start all scheduled tasks."""
        await self._start_portfolio_updates()
        await self._start_alert_checking()
        await self._start_daily_snapshots()

    async def stop(self):
        """Stop all running tasks."""
        for task in self.running_tasks.values():
            task.cancel()
        self.running_tasks.clear()

    async def add_portfolio_update_task(self, user_id: int, interval: int = None):
        """Add a new portfolio update task for a user."""
        task_name = f"portfolio_update_{user_id}"
        if task_name in self.running_tasks:
            self.running_tasks[task_name].cancel()
        
        interval = interval or self.update_interval
        self.running_tasks[task_name] = asyncio.create_task(
            self._portfolio_update_loop(user_id, interval)
        )

    async def _start_portfolio_updates(self):
        """Start portfolio update tasks for all users."""
        try:
            users = await self.db.get_all_users()
            for user in users:
                await self.add_portfolio_update_task(user.user_id)
        except Exception as e:
            print(f"Error starting portfolio updates: {e}")

    async def _start_alert_checking(self):
        """Start alert checking task."""
        if self.alerts_manager:
            self.running_tasks['alert_checker'] = asyncio.create_task(
                self.alerts_manager.check_all_alerts()
            )

    async def _start_daily_snapshots(self):
        """Start daily portfolio snapshot task."""
        self.running_tasks['daily_snapshots'] = asyncio.create_task(
            self._daily_snapshot_loop()
        )

    async def _portfolio_update_loop(self, user_id: int, interval: int):
        """Periodic portfolio update loop for a user."""
        while True:
            try:
                # Get user's portfolios
                portfolios = await self.db.get_user_portfolios(user_id)
                
                for portfolio in portfolios:
                    # Get portfolio data
                    holdings = await self.portfolio_fetcher.get_portfolio_holdings(portfolio)
                    
                    if holdings:
                        # Save current snapshot
                        await self.db.save_portfolio_snapshot(
                            user_id=user_id,
                            portfolio_id=portfolio.portfolio_id,
                            total_value=holdings['total_value'],
                            token_balances=holdings['chains']
                        )
                        
                        # Check if significant changes occurred
                        if await self._should_notify_changes(portfolio.portfolio_id, holdings):
                            await self.notifier.send_portfolio_summary(user_id, holdings)
                
            except Exception as e:
                print(f"Error in portfolio update loop for user {user_id}: {e}")
            
            await asyncio.sleep(interval)

    async def _daily_snapshot_loop(self):
        """Take daily snapshots of all portfolios."""
        while True:
            try:
                # Get all users
                users = await self.db.get_all_users()
                
                for user in users:
                    portfolios = await self.db.get_user_portfolios(user.user_id)
                    
                    for portfolio in portfolios:
                        holdings = await self.portfolio_fetcher.get_portfolio_holdings(portfolio)
                        
                        if holdings:
                            await self.db.save_portfolio_snapshot(
                                user_id=user.user_id,
                                portfolio_id=portfolio.portfolio_id,
                                total_value=holdings['total_value'],
                                token_balances=holdings['chains']
                            )
                
            except Exception as e:
                print(f"Error in daily snapshot loop: {e}")
            
            # Wait until next day
            await self._wait_until_next_day()

    async def _should_notify_changes(self, portfolio_id: int, current_holdings: Dict) -> bool:
        """
        Determine if user should be notified of portfolio changes.
        Checks for significant value changes (>5%) or new tokens.
        """
        try:
            # Get last snapshot
            last_snapshot = await self.db.get_latest_snapshot(portfolio_id)
            if not last_snapshot:
                return True

            # Calculate value change percentage
            value_change = (
                (current_holdings['total_value'] - last_snapshot.total_value)
                / last_snapshot.total_value * 100
            )

            # Notify if value changed more than 5%
            if abs(value_change) >= 5:
                return True

            # Check for new tokens
            old_tokens = set()
            for chain_data in last_snapshot.token_balances.values():
                old_tokens.update(chain_data['tokens'].keys())

            new_tokens = set()
            for chain_data in current_holdings['chains'].values():
                new_tokens.update(chain_data['tokens'].keys())

            # Notify if there are new tokens
            if new_tokens - old_tokens:
                return True

            return False

        except Exception as e:
            print(f"Error checking portfolio changes: {e}")
            return False

    async def _wait_until_next_day(self):
        """Wait until the start of the next day."""
        now = datetime.utcnow()
        next_day = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        await asyncio.sleep((next_day - now).total_seconds())

    async def check_premium_expirations_loop(self):
        """Periodically check for expired premium users and revert their status."""
        while True:
            try:
                expired_users = await self.db.get_expired_premium_users()
                for user in expired_users:
                    logger.info(f"Premium expired for user {user.user_id}. Reverting to standard plan.")
                    await self.db.set_user_premium_status(user.user_id, is_premium=False)
                    await self.notifier.send_message(
                        user.user_id,
                        "Your premium subscription has expired. You have been reverted to the standard plan."
                    )
            except Exception as e:
                logger.error(f"Error in premium expiration loop: {e}")
            
            await asyncio.sleep(self.premium_check_interval)
