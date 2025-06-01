import logging
import re
from typing import Literal, Optional

# Attempt to import Web3 and base58, handling potential ImportErrors
try:
    from web3 import Web3
    WEB3_AVAILABLE = True
except ImportError:
    WEB3_AVAILABLE = False
    Web3 = None # To avoid NameError if referenced later without checking WEB3_AVAILABLE
    logging.getLogger(__name__).warning(
        "web3 library not found. EVM address validation will be unavailable."
    )

try:
    import base58
    BASE58_AVAILABLE = True
except ImportError:
    BASE58_AVAILABLE = False
    base58 = None # To avoid NameError
    logging.getLogger(__name__).warning(
        "base58 library not found. Stronger Solana address validation (decode check) will be unavailable; "
        "falling back to regex only for Solana."
    )

logger = logging.getLogger(__name__)

# Define AddressType using Literal for better type hinting
AddressType = Literal["evm", "solana"]

class WalletManager:
    """
    Manages wallet address validation and type identification for EVM and Solana chains.
    """

    # Regex for Solana address: Base58 characters, 32-44 length
    # (Derived from typical Solana public key structure)
    SOLANA_ADDRESS_REGEX = r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"

    def _is_valid_evm_address(self, address: str) -> bool:
        """
        Checks if the address is a valid EVM address format.
        Relies on the web3.py library.
        """
        if not WEB3_AVAILABLE:
            logger.debug("web3 library not available, cannot validate EVM address.")
            return False
        try:
            return Web3.is_address(address)
        except Exception as e: # Catch any unexpected error from Web3.is_address
            logger.error(f"Error during EVM address validation for '{address}': {e}")
            return False

    def _is_valid_solana_address(self, address: str) -> bool:
        """
        Checks if the address is a valid Solana address format.
        Uses regex and, if available, base58 decoding for stronger validation.
        """
        if not isinstance(address, str): # Basic type check
            return False

        # 1. Regex check for character set and length
        if not re.fullmatch(self.SOLANA_ADDRESS_REGEX, address):
            return False

        # 2. Stronger check: Base58 decoding (if library is available)
        if BASE58_AVAILABLE:
            try:
                base58.b58decode(address)
                # Further check: Solana public keys are typically 32 bytes when decoded.
                # This is a common characteristic but not universally strict for all base58 strings.
                # For wallet addresses, it's a strong indicator.
                if len(base58.b58decode(address)) == 32:
                    return True
                else:
                    logger.debug(
                        f"Address {address} passed Base58 decode but not 32 bytes long ({len(base58.b58decode(address))} bytes)."
                    )
                    return False # Or True, if you want to be less strict post-decode
            except ValueError: # If b58decode fails
                logger.debug(f"Address {address} matched Solana regex but failed Base58 decode.")
                return False
            except Exception as e: # Catch any other unexpected error from base58.b58decode
                logger.error(f"Error during Solana address Base58 decoding for '{address}': {e}")
                return False
        else:
            # If base58 library is not available, rely on regex match.
            # Log that a weaker validation is being performed.
            logger.debug(
                f"base58 library not available. Address {address} validated as Solana based on regex only."
            )
            return True # Regex match is our best effort without the library

    async def validate_address(self, address: str) -> bool:
        """
        Validates if the given address is a recognized EVM or Solana address format.

        Args:
            address: The wallet address string to validate.

        Returns:
            True if the address is a valid EVM or Solana address, False otherwise.
        """
        if not isinstance(address, str) or not address:
            logger.debug("Validation failed: Address is empty or not a string.")
            return False

        logger.debug(f"Attempting to validate address: {address}")

        if self._is_valid_evm_address(address):
            logger.info(f"Address {address} validated as EVM.")
            return True

        if self._is_valid_solana_address(address):
            logger.info(f"Address {address} validated as Solana.")
            return True

        logger.warning(f"Address {address} failed validation (unrecognized format or invalid).")
        return False

    async def get_address_type(self, address: str) -> Optional[AddressType]:
        """
        Attempts to determine the type (evm or solana) of a given address.

        Args:
            address: The wallet address string.

        Returns:
            'evm', 'solana', or None if the type cannot be determined or is invalid.
        """
        if not isinstance(address, str) or not address:
            return None

        logger.debug(f"Attempting to determine type for address: {address}")

        # EVM check is usually more specific due to checksum and prefix
        if self._is_valid_evm_address(address):
            logger.debug(f"Address {address} identified as EVM type.")
            return "evm"

        # Solana check
        if self._is_valid_solana_address(address):
            logger.debug(f"Address {address} identified as Solana type.")
            return "solana"

        logger.debug(f"Could not determine type for address: {address}")
        return None
    
