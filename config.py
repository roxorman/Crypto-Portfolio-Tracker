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
        
        # Database Configuration
        self.DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
        
        # Bot Configuration
        self.COMMANDS = {
            'start': 'Start using the bot',
            'addwallet': 'Add a new wallet to track',
            'removewallet': 'Remove a tracked wallet',
            'summary': 'Get portfolio summary',
            'setalert': 'Set a new alert',
            'removealert': 'Remove an existing alert'
        }

        # Portfolio Configuration
        self.MIN_TOKEN_VALUE_USD = 1  # Minimum USD value to include token in portfolio
        self.UPDATE_INTERVAL = 3600  # Default update interval in seconds

        if not self.TELEGRAM_TOKEN or not self.DATABASE_URL:
            raise ValueError("TELEGRAM_TOKEN and DATABASE_URL must be set in .env")
        
    @staticmethod
    def get_api_key() -> str:
        """Get the Alchemy API key from environment variables."""
        api_key = os.getenv('ALCHEMY_API_KEY')
        if not api_key:
            raise ValueError("ALCHEMY_API_KEY not found in environment variables")
        return api_key