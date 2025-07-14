# utils.py
from typing import Dict, List, Union, Optional, Tuple, Any # Added Optional, Tuple, Any
from decimal import Decimal
from datetime import datetime, timedelta
import json
from config import Config
import math

def normalize_chain_name(chain: str) -> str:
    """
    Normalize blockchain name for consistent usage.
    Maps common short names to full names.
    """
    chain = chain.lower().strip()
    chain_mapping = {
        'eth': 'ethereum',
        'arb': 'arbitrum',
        'opt': 'optimism',
        'poly': 'polygon',
        'avax': 'avalanche',
        # Add more here...
        # 'sol': 'solana' # If adding non-EVM
    }
    return chain_mapping.get(chain, chain)

def parse_view_args(args: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Parses arguments for view-like commands to extract an identifier
    and an optional chain filter (e.g., "chain:base").
    """
    if not args:
        return None, None
    identifier = args[0]
    chain_filter = None
    for arg in args[1:]:
        if arg.lower().startswith("chain:"):
            chain_part = arg.split(":", 1)[1]
            if chain_part:
                chain_filter = normalize_chain_name(chain_part)
            break
    return identifier, chain_filter

# ... (rest of your existing utils.py content: format_address, format_currency, etc.)
def format_address(address: str, start_len: int = 6, end_len: int = 4) -> str:
    """
    Format Ethereum address for display (e.g., 0x1234...5678).
    Allows customizing displayed length.
    """
    if not address:
        return "N/A"
    if not isinstance(address, str) or len(address) < start_len + end_len + 2: # Basic check
        return address # Return original if not typical address format
    return f"{address[:start_len]}...{address[-end_len:]}"


def format_currency(amount: Union[float, Decimal], decimals: int = 2, currency: str = "USD") -> str:
    """
    Format currency amount with symbol.
    """
    formatted = f"{float(amount):,.{decimals}f}"
    if currency == "USD":
        return f"${formatted}"
    # Add other currency symbols if needed
    # elif currency == "EUR":
    #    return f"€{formatted}"
    return f"{formatted} {currency}"

def format_crypto_amount(amount: Union[float, Decimal], symbol: str, decimals: int = 6) -> str:
    """
    Format crypto amount with token symbol. Handles potential precision.
    """
    try:
        # Attempt to format with specified decimals
        formatted = f"{float(amount):,.{decimals}f}"
        # Remove trailing zeros after the decimal point for cleaner display if decimals > 0
        if decimals > 0 and '.' in formatted:
             formatted = formatted.rstrip('0').rstrip('.')
    except (ValueError, TypeError):
        formatted = str(amount) # Fallback if formatting fails

    return f"{formatted} {symbol}" if symbol else formatted


def calculate_percentage_change(old_value: float, new_value: float) -> float:
    """
    Calculate percentage change between two values. Handles old_value being zero.
    """
    if old_value is None or new_value is None:
        return 0.0 # Or handle as error/None depending on context
    try:
        old_value = float(old_value)
        new_value = float(new_value)
        if old_value == 0:
            return float('inf') if new_value > 0 else (float('-inf') if new_value < 0 else 0.0) # Handle division by zero
        return ((new_value - old_value) / old_value) * 100.0
    except (ValueError, TypeError):
        return 0.0 # Fallback for non-numeric input


def format_percentage(value: float, include_sign: bool = True) -> str:
    """
    Format percentage value for display. Handles None or non-float values.
    """
    if value is None:
        return "N/A"
    try:
        value = float(value)
        formatted = f"{abs(value):.2f}%"
        if include_sign:
            if value > 0:
                return f"+{formatted}"
            elif value < 0:
                return f"-{formatted}"
            else: # value == 0 or is NaN etc.
                return f" {formatted}" # Space for alignment maybe? Or just formatted
        return formatted
    except (ValueError, TypeError):
        return "N/A" # Error formatting


def format_timeframe(timeframe: str) -> tuple[datetime, datetime]:
    """
    Convert timeframe string to start and end datetime.
    Examples: '1H', '24H', '7D', '30D', '1Y'
    """
    now = datetime.utcnow()

    units = {
        'H': 'hours',
        'D': 'days',
        'W': 'weeks', # Added weeks
        'M': 'months', # Approx. 30 days for simplicity, refine if needed
        'Y': 'years'
    }

    try:
        amount = int(timeframe[:-1])
        unit = timeframe[-1].upper()

        if unit not in units:
            raise ValueError(f"Invalid timeframe unit: {unit}")

        if unit == 'M': # Approximate months
             delta_args = {'days': amount * 30}
        elif unit == 'Y': # Approximate years
             delta_args = {'days': amount * 365}
        else:
             delta_args = {units[unit]: amount}

        start_time = now - timedelta(**delta_args)

        return start_time, now
    except (ValueError, IndexError, TypeError):
         # Handle invalid format like 'D', '1', '1Z' etc.
         raise ValueError(f"Invalid timeframe format: '{timeframe}'. Use format like '24H', '7D', '1M', '1Y'.")


def validate_json(json_str: str) -> bool:
    """
    Validate if a string is valid JSON.
    """
    if not isinstance(json_str, str):
        return False
    try:
        json.loads(json_str)
        return True
    except json.JSONDecodeError:
        return False

def safe_division(numerator: Union[int, float], denominator: Union[int, float], default: float = 0.0) -> float:
    """
    Safely divide numbers, returning default value if denominator is 0 or invalid input.
    """
    try:
        num = float(numerator)
        den = float(denominator)
        if den == 0:
            return float(default)
        return num / den
    except (ValueError, TypeError, ZeroDivisionError):
        return float(default)


def chunk_list(lst: List, chunk_size: int) -> List[List]:
    """
    Split a list into chunks of specified size. Handles edge cases.
    """
    if not isinstance(lst, list) or not isinstance(chunk_size, int) or chunk_size <= 0:
        return [lst] # Return original list in a list, or handle error as needed
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

# Import PortfolioFetcher for type hinting, ensure no circular dependency issues.
# If api_fetcher imports utils, this might need careful structuring or moving the function.
# For now, assuming utils.py can import from api_fetcher.py without circularity.
# If circularity is an issue, this function might be better placed in a different module
# or api_fetcher_instance passed as 'Any'.
from api_fetcher import PortfolioFetcher # Added for type hint
import logging # Add logging for utils if not already present

logger = logging.getLogger(__name__) # Add logger for utils

async def get_token_info_from_contract_address(api_fetcher_instance: PortfolioFetcher, contract_address: str) -> Optional[Dict[str, Any]]:
    """
    Fetches token information using a contract address from CMC.

    Args:
        api_fetcher_instance: An instance of the PortfolioFetcher class.
        contract_address: The contract address of the token.

    Returns:
        A dictionary containing the token's metadata (id, name, symbol, slug, etc.)
        if found and contains a slug, otherwise None.
    """
    if not contract_address:
        logger.debug("get_token_info_from_contract_address: No contract address provided.")
        return None

    token_info = await api_fetcher_instance.get_token_info_by_contract_address(contract_address)
    
    if token_info and isinstance(token_info, dict) and 'slug' in token_info and isinstance(token_info['slug'], str):
        logger.debug(f"Successfully retrieved token_info with slug for address {contract_address}.")
        return token_info # Return the whole dictionary
    else:
        if token_info:
            logger.warning(f"Retrieved token_info for address {contract_address} but slug is missing or invalid: {token_info}")
        else:
            logger.debug(f"No token_info retrieved by api_fetcher for address {contract_address}.")
        return None

def get_cmc_slug(address: str) -> Optional[str]:
    """
    Get CoinMarketCap slug from address and chain.
    Returns None if not found or invalid input.
    """
    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/info"
    params = {
        'address': address,
    }
    headers = {
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': Config.COINMARKETCAP_API_KEY,  # Use the API key from config
    }

def format_price_dynamically(price: float, significant_digits: int = 4) -> str:
    """
    Formats a price to a string with a specified number of significant digits.
    Handles very small numbers by using scientific notation if necessary for precision,
    or general formatting for typical prices.
    Aims to avoid "$0.0000" for small, non-zero prices.
    """
    if price == 0:
        return "0.00" # Or simply "0"
    
    # Determine the number of decimal places needed to show the first significant digit
    # For example, if price is 0.0001234, and significant_digits is 4, we want to show 0.0001234
    # If price is 0.0000001234, we want 0.0000001234
    # If price is 12.3456, we want 12.35 (if significant_digits implies 2 decimal places for numbers > 1)
    # If price is 123.456, we want 123.5
    # If price is 1234.56, we want 1235

    if abs(price) < 1e-4 and abs(price) > 0: # For very small numbers, show more precision or use 'g' format
        # Try to format to show up to 'significant_digits' *after* leading zeros
        # This is tricky with standard formatters directly.
        # A simple approach for very small numbers:
        s = f"{price:.{significant_digits + int(abs(math.log10(abs(price))))}f}" 
        # Trim trailing zeros if it results in them, but ensure it doesn't become "0.0000" if it's not zero
        s_trimmed = s.rstrip('0')
        if s_trimmed.endswith('.'):
            s_trimmed += '0' # Avoid "0."
        # If it becomes "0.0" or "0", but original price was not 0, use a more general format
        if float(s_trimmed) == 0 and price != 0:
             return f"{price:.{significant_digits}g}" # Use general format for very small numbers
        return s_trimmed
    
    # For numbers >= 0.0001 or < -0.0001
    # Use a method to determine decimal places based on magnitude and significant digits
    if abs(price) >= 1:
        # For numbers >= 1, significant digits mostly affect decimals
        # Example: 12.3456 with 4 sig digits -> 12.35 (2 decimals)
        # Example: 1.23456 with 4 sig digits -> 1.235 (3 decimals)
        # Example: 1234.56 with 4 sig digits -> 1235 (0 decimals)
        # Example: 12345.6 with 4 sig digits -> 12350 (approx, or use 'g')
        
        # Let's try a simpler approach: format to a reasonable number of decimals,
        # then refine if it's too many or too few for "significance".
        # This is a common heuristic:
        if abs(price) >= 1000:
            decimals = 0
        elif abs(price) >= 100:
            decimals = 1
        elif abs(price) >= 1:
            decimals = 2
        elif abs(price) >= 0.01:
            decimals = 4
        else: # < 0.01 but not extremely small (handled above)
            decimals = 6 # Show a few more for smaller numbers
            
        # Ensure we don't show excessive precision if the number is simple
        formatted_price = f"{price:,.{decimals}f}"
        # If after formatting, it's like "12.00" and we only needed "12", this is fine.
        # The main goal is to avoid "$0.0000" for non-zero small values.
        # Let's refine the number of decimals to show *at least* `significant_digits` if possible,
        # without being excessive for large numbers.

        # A more direct way for significant figures:
        # This format specifier '{value:.{precision}g}' attempts to show 'precision' significant figures.
        return f"{price:.{significant_digits}g}"

    # Fallback for numbers between 1e-4 and 0.01 (or numbers not caught above)
    # This ensures we show enough decimal places for these.
    # The '.{significant_digits}g' should handle this reasonably.
    return f"{price:.{significant_digits}g}"

def split_message(message: str, max_length: int = 4096) -> List[str]:
    """
    Splits a message into chunks of a specified max_length, ensuring that
    MarkdownV2 formatting is not broken across chunks.
    """
    if len(message) <= max_length:
        return [message]

    chunks = []
    current_chunk = ""
    lines = message.split('\n')

    for line in lines:
        # If a single line is too long, it must be split, which is complex.
        # For now, we assume lines are not longer than max_length.
        # A more robust solution would split the line itself.
        if len(line) > max_length:
            # Handle extremely long lines if necessary, for now, we'll truncate
            # or find a way to split them without breaking markdown.
            # This is a simplification for this example.
            line = line[:max_length - 5] + "..."

        if len(current_chunk) + len(line) + 1 > max_length:
            chunks.append(current_chunk)
            current_chunk = line
        else:
            if current_chunk:
                current_chunk += "\n" + line
            else:
                current_chunk = line
    
    if current_chunk:
        chunks.append(current_chunk)

    return chunks
# Need to import math for log10
