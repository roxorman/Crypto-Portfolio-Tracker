from dotenv import load_dotenv
import os

class Config:
    """Configuration class to handle all environment variables and settings."""
    
    def __init__(self):
        load_dotenv()
        
        # API Keys and Tokens
        self.TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
        self.ALCHEMY_API_KEY = os.getenv('ALCHEMY_API_KEY')
        self.MORALIS_API_KEY = os.getenv('MORALIS_API_KEY')
        self.MOBULA_API_KEY = os.getenv('MOBULA_API_KEY')
        self.COINMARKETCAP_API_KEY = os.getenv('COINMARKETCAP_API_KEY') # Added CoinMarketCap API Key
        self.ZERION_API_KEY = os.getenv('ZERION_API_KEY')
        self.COINGECKO_API_KEY = os.getenv('COINGECKO_API_KEY')
        
        # Database Configuration
        self.DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
        
        # --- NEW: Admin and Tier Configuration ---
        admin_ids_str = os.getenv('ADMIN_USER_IDS', '')
        self.ADMIN_USER_IDS = [int(uid.strip()) for uid in admin_ids_str.split(',') if uid.strip()]

        self.FREE_TIER_CONFIG = {
            "MAX_WALLETS": 3,
            "MAX_ALERTS": 3,
            "MAX_API_CALLS_PER_DAY": 10
        }
        
        self.PREMIUM_TIER_CONFIG = {
            "MAX_WALLETS": 10,
            "MAX_ALERTS": 10,
            "MAX_API_CALLS_PER_DAY": 30
        }
        # --- END NEW ---

        if not self.TELEGRAM_TOKEN or not self.DATABASE_URL:
            raise ValueError("TELEGRAM_TOKEN and DATABASE_URL must be set in .env")
        if not self.ADMIN_USER_IDS:
            print("WARNING: ADMIN_USER_IDS is not set in .env. Admin commands will not work.")

    def get_user_tier_config(self, is_premium: bool) -> dict:
        """Returns the appropriate tier configuration dictionary for a user."""
        return self.PREMIUM_TIER_CONFIG if is_premium else self.FREE_TIER_CONFIG
