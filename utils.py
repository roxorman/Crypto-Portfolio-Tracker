from typing import Dict, List, Union
from decimal import Decimal
from datetime import datetime, timedelta
import json

def normalize_chain_name(chain: str) -> str:
    """
    Normalize blockchain name for consistent usage.
    Maps common short names to full names.
    """
    chain = chain.lower().strip()
    # Add more mappings as needed
    chain_mapping = {
        'eth': 'ethereum',
        'arb': 'arbitrum',
        'opt': 'optimism',
        'poly': 'polygon',
        'avax': 'avalanche',
        # Add more here...
        # 'sol': 'solana' # If adding non-EVM
    }
    return chain_mapping.get(chain, chain) # Return mapped name or original if no map

# Use the 0x1234...5678 version
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