import asyncio
from functools import wraps
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

from db_manager import DatabaseManager
from config import Config
from models import User

def api_rate_limit(func):
    """
    A decorator that checks and enforces API call rate limits for a user.
    This decorator should be applied to methods of a handler class that has
    `self.db` (DatabaseManager) and `self.config` (Config) attributes.
    """
    @wraps(func)
    async def wrapper(self, update: Update, *args, **kwargs):
        # The first argument is now 'self' (the class instance)
        # The second argument is 'update'
        if not hasattr(self, 'db') or not hasattr(self, 'config'):
            raise AttributeError("The 'api_rate_limit' decorator requires the class instance to have 'db' and 'config' attributes.")
        
        db: DatabaseManager = self.db
        config: Config = self.config

        user_id = update.effective_user.id
        async with db.async_session() as session:
            user = await session.get(User, user_id)
            if not user:
                await update.effective_message.reply_text("Could not find your user profile. Please try /start again.")
                return

            tier_config = config.get_user_tier_config(user.is_premium)
            limit = tier_config["MAX_API_CALLS_PER_DAY"]

            now_utc = datetime.now(timezone.utc)
            if user.last_api_call_at and user.last_api_call_at.date() < now_utc.date():
                user.api_call_count = 0

            if user.api_call_count >= limit:
                remaining_calls = limit - user.api_call_count
                await update.effective_message.reply_text(
                    f"You have reached your daily API request limit of {limit} calls. "
                    f"Please try again tomorrow or upgrade to Premium for a higher limit.\n\n"
                    f"_(Calls remaining: {max(0, remaining_calls)})_"
                )
                return

            user.api_call_count += 1
            user.last_api_call_at = now_utc
            await session.commit()
        
        # Execute the original function (e.g., self.handle_view_selection(update, *args, **kwargs))
        return await func(self, update, *args, **kwargs)
    return wrapper