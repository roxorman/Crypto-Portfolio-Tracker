from web3 import Web3
import logging
import re # Import re for regex

logger = logging.getLogger(__name__)

class WalletManager:
    """Manages wallet validation and potentially other wallet-related utilities."""

    async def validate_address(self, address: str) -> bool:
        """
        Validates if the address is a valid EVM or Solana address format.
        """
        logger.debug(f"Validating address: {address}")

        # 1. Check for EVM address format (checksummed or not)
        if Web3.is_address(address):
            logger.debug(f"Address {address} validated as EVM.")
            return True

        # 2. Check for Solana address format (Base58, 32-44 chars)
        # Solana addresses use Base58 characters (1-9, A-H, J-N, P-Z, a-k, m-z)
        # Regex: ^[1-9A-HJ-NP-Za-km-z]{32,44}$
        solana_pattern = r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"
        if re.fullmatch(solana_pattern, address): # Use fullmatch for exact string match
            logger.debug(f"Address {address} validated as Solana (regex match).")
            # Optional: Add base58 decode check for stronger validation if needed
            # try:
            #     import base58
            #     base58.b58decode(address)
            #     logger.debug(f"Address {address} successfully decoded as Base58.")
            #     return True
            # except ImportError:
            #     logger.warning("base58 library not installed, skipping decode check for Solana address.")
            #     return True # Rely on regex if library missing
            # except ValueError:
            #     logger.warning(f"Address {address} matched Solana regex but failed Base58 decode.")
            #     return False
            return True # Relying on regex for now

        # 3. Add checks for other address types here if needed (e.g., Tron, Bitcoin)

        logger.warning(f"Address {address} failed validation (unrecognized format).")
        return False

    # Potential future methods:
    # async def get_address_type(self, address: str) -> Optional[str]:
    #     """Attempts to determine the type (evm, solana, etc.) of an address."""
    #     if Web3.is_address(address):
    #         return "evm"
    #     solana_pattern = r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"
    #     if re.fullmatch(solana_pattern, address):
    #         # Add base58 check here for higher confidence if library is available
    #         return "solana"
    #     return None
