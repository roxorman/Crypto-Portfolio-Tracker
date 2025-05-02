from telegram import Update
from telegram.ext import ContextTypes
from db_manager import DatabaseManager
from wallet_manager import WalletManager
from api_fetcher import PortfolioFetcher
from alerts_manager import AlertsManager
from notifier import Notifier
from scheduler import Scheduler
from portfolio_analyzer import PortfolioAnalyzer # Import PortfolioAnalyzer
from utils import normalize_chain_name, format_address
import re
import logging
import json # Import json for debugging raw data
from telegram.helpers import escape_markdown # Import escape_markdown
import asyncio # Import asyncio for async tasks
from collections import defaultdict # Import defaultdict for grouping
from typing import List, Dict, Optional, Tuple, Any # For type hinting
from web3 import Web3 # Import Web3 for EVM check

logger = logging.getLogger(__name__) # Add logger

class BotHandlers:
    """
    Handles incoming Telegram bot commands and interactions.
    """
    def __init__(self, db_manager: DatabaseManager, wallet_manager: WalletManager,
                 portfolio_fetcher: PortfolioFetcher, alerts_manager: AlertsManager,
                 notifier: Notifier, scheduler: Scheduler, portfolio_analyzer: PortfolioAnalyzer): # Added portfolio_analyzer
        self.db = db_manager
        self.wallet_manager = wallet_manager
        self.portfolio_fetcher = portfolio_fetcher
        self.alerts_manager = alerts_manager
        self.notifier = notifier
        self.scheduler = scheduler
        self.portfolio_analyzer = portfolio_analyzer # Store PortfolioAnalyzer instance
        logger.info("BotHandlers initialized.") # Add log

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /start command"""
        user = update.effective_user
        # Ensure user exists in DB before proceeding
        db_user = await self.db.create_user(user.id, user.username, user.first_name)
        if db_user:
             logger.info(f"User {user.id} started or interacted.")
             await self.notifier.send_welcome_message(user.id, user.first_name or "there") # Use first_name or fallback
        else:
             logger.error(f"Failed to create or retrieve user {user.id} in DB.")
             await update.message.reply_text("Sorry, there was an error setting up your profile. Please try again later.")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /help command"""
        await self.notifier.send_help_message(update.effective_user.id)

    async def portfolio_create(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles the /portfolio_create command.
        Expected format: /portfolio_create <Name> [Description...]
        """
        user_id = update.effective_user.id
        args = context.args

        if not args:
            await update.message.reply_text("Usage: /portfolio_create <Name> [Description...]\nExample: `/portfolio_create My Main Holdings`")
            return

        name = args[0]
        description = " ".join(args[1:]) if len(args) > 1 else ""

        logger.info(f"User {user_id} attempting to create portfolio '{name}'")
        portfolio = await self.db.create_portfolio(user_id, name, description)

        if portfolio:
            logger.info(f"Portfolio '{name}' (ID: {portfolio.portfolio_id}) created for user {user_id}")
            await update.message.reply_text(f"✅ Portfolio '{name}' created successfully!")
        else:
            # Check if it failed because the name already exists
            existing = await self.db.get_portfolio_by_name(user_id, name)
            if existing:
                 logger.warning(f"User {user_id} failed to create portfolio '{name}' - already exists.")
                 await update.message.reply_text(f"❌ Failed to create portfolio. A portfolio named '{name}' already exists.")
            else:
                 logger.error(f"User {user_id} failed to create portfolio '{name}' - unknown DB error.")
                 await update.message.reply_text("❌ Failed to create portfolio. An unexpected error occurred. Please try again.")

    async def portfolio_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles the /portfolio_list command to list user's portfolios.
        """
        user_id = update.effective_user.id
        logger.info(f"User {user_id} requested portfolio list.")
        portfolios = await self.db.get_user_portfolios(user_id)

        if not portfolios:
            await update.message.reply_text("You don't have any portfolios yet. Use `/portfolio_create <Name>` to create one.")
            return

        message = "📂 Your Portfolios:\n"
        for p in portfolios:
            # Escape name and description for MarkdownV2
            safe_name = escape_markdown(p.name, version=2)
            message += f"\n\\- `{safe_name}`" # Escape dash, use code block
            if p.description:
                safe_desc = escape_markdown(p.description, version=2)
                message += f" \\({safe_desc}\\)" # Escape parens

        # Send with MarkdownV2, ensure notifier handles it
        await self.notifier.send_message(update.effective_user.id, message, parse_mode='MarkdownV2')

    async def portfolio_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles the /portfolio_delete command.
        Expected format: /portfolio_delete <Name>
        """
        user_id = update.effective_user.id
        args = context.args

        if not args:
            await update.message.reply_text("Usage: /portfolio_delete <PortfolioName>")
            return

        name = args[0]
        logger.info(f"User {user_id} attempting to delete portfolio '{name}'")
        success = await self.db.delete_portfolio(user_id, name)

        safe_name = escape_markdown(name, version=2)
        if success:
            logger.info(f"Portfolio '{name}' deleted successfully for user {user_id}")
            await update.message.reply_text(f"🗑️ Portfolio '{safe_name}' deleted successfully\\.", parse_mode='MarkdownV2')
        else:
            logger.warning(f"Failed to delete portfolio '{name}' for user {user_id} (not found or error).")
            await update.message.reply_text(f"❌ Portfolio '{safe_name}' not found or could not be deleted\\.", parse_mode='MarkdownV2')

    async def portfolio_rename(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles the /portfolio_rename command.
        Expected format: /portfolio_rename <OldName> <NewName>
        """
        user_id = update.effective_user.id
        args = context.args

        if len(args) != 2:
            await update.message.reply_text("Usage: /portfolio_rename <OldName> <NewName>")
            return

        old_name, new_name = args
        logger.info(f"User {user_id} attempting to rename portfolio '{old_name}' to '{new_name}'")
        success = await self.db.rename_portfolio(user_id, old_name, new_name)

        safe_old_name = escape_markdown(old_name, version=2)
        safe_new_name = escape_markdown(new_name, version=2)

        if success:
            logger.info(f"Portfolio '{old_name}' renamed to '{new_name}' for user {user_id}")
            await update.message.reply_text(f"✏️ Portfolio '{safe_old_name}' renamed to '{safe_new_name}'\\.", parse_mode='MarkdownV2')
        else:
            existing_old = await self.db.get_portfolio_by_name(user_id, old_name)
            existing_new = await self.db.get_portfolio_by_name(user_id, new_name)
            if not existing_old:
                 logger.warning(f"Rename failed for user {user_id}: Old portfolio '{old_name}' not found.")
                 await update.message.reply_text(f"❌ Portfolio '{safe_old_name}' not found\\.", parse_mode='MarkdownV2')
            elif existing_new:
                 logger.warning(f"Rename failed for user {user_id}: New name '{new_name}' already exists.")
                 await update.message.reply_text(f"❌ Cannot rename: a portfolio named '{safe_new_name}' already exists\\.", parse_mode='MarkdownV2')
            else:
                 logger.error(f"Rename failed for user {user_id}: Unknown error renaming '{old_name}' to '{new_name}'.")
                 await update.message.reply_text(f"❌ Failed to rename portfolio '{safe_old_name}'\\. An unexpected error occurred\\.", parse_mode='MarkdownV2')

    async def portfolio_add_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        /portfolio_add_wallet <PortfolioName> <Address> [Chain] [Label...]
        Chain is ignored if Address is a Solana address.
        """
        user_id = update.effective_user.id
        args = context.args

        if len(args) < 2:
            await update.message.reply_text(
                "Usage: /portfolio_add_wallet <PortfolioName> <Address> [Chain] [Label...]\n"
                "Example EVM: `/portfolio_add_wallet MyStuff 0x123...abc base Main Wallet`\n"
                "Example Solana: `/portfolio_add_wallet SolStuff 6EXX...QLMG My Solana Wallet`"
            )
            return

        portfolio_name, address = args[0], args[1]
        extra_args = args[2:] # Arguments after portfolio name and address

        logger.info(f"User {user_id} attempting to add wallet {address} to '{portfolio_name}' with extra args: {extra_args}")

        # 1. Validate address first
        if not await self.wallet_manager.validate_address(address):
            safe_address = escape_markdown(address, version=2)
            await update.message.reply_text(f"❌ Invalid or unsupported wallet address format: `{safe_address}`\\.", parse_mode='MarkdownV2')
            return

        # 2. Determine wallet type
        wallet_type = "unknown"
        if Web3.is_address(address):
            wallet_type = "evm"
        else:
            solana_pattern = r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"
            if re.fullmatch(solana_pattern, address):
                wallet_type = "solana"

        if wallet_type == "unknown":
             logger.error(f"Address {address} passed validation but type could not be determined.")
             safe_address = escape_markdown(address, version=2)
             await update.message.reply_text(f"❌ Could not determine wallet type for address `{safe_address}`\\. Please report this issue\\.", parse_mode='MarkdownV2')
             return

        logger.info(f"Determined wallet type as '{wallet_type}' for address {address}")

        # 3. Parse chain and label based on wallet type
        chain: Optional[str] = None
        label: Optional[str] = None

        if wallet_type == "solana":
            # For Solana, ignore any chain input, treat all extra args as label
            chain = None # Explicitly set chain to None for Solana associations
            label = " ".join(extra_args) if extra_args else None
            logger.info(f"Solana wallet detected. Ignoring chain input. Label derived from extra args: '{label}'")
        elif wallet_type == "evm":
            # For EVM, parse chain and label as before
            chain, label = self._parse_chain_and_label(extra_args)
            logger.info(f"EVM wallet detected. Parsed Chain: '{chain}', Label: '{label}'")
        # Add elif for other wallet types here if needed

        # 4. Handle default label if still None/empty (will be handled in DB if None)
        if not label:
             logger.info("Label was empty, will use default in DB.")
             label = None # Ensure it's None if empty string

        # 5. Get portfolio
        portfolio = await self.db.get_portfolio_by_name(user_id, portfolio_name)
        if not portfolio:
            safe_portfolio_name = escape_markdown(portfolio_name, version=2)
            await update.message.reply_text(f"❌ Portfolio '{safe_portfolio_name}' not found\\. Use `/portfolio_list`\\.", parse_mode='MarkdownV2')
            return

        # 6. Add wallet identity (using detected type)
        # Use default label if needed within add_wallet_identity
        wallet_identity = await self.db.add_wallet_identity(user_id, address, wallet_type, label)
        if not wallet_identity:
            # This usually means the wallet address already exists for the user
            # Let's try to retrieve it to proceed with linking
            wallet_identity = await self.db.find_user_wallet(user_id, address)
            if not wallet_identity:
                 logger.error(f"Failed to add or retrieve wallet identity for user {user_id}, address {address}")
                 await update.message.reply_text("❌ Internal error while saving or retrieving wallet\\. Try again\\.", parse_mode='MarkdownV2')
                 return
            else:
                 logger.info(f"Wallet identity for {address} already existed (ID: {wallet_identity.wallet_id}), proceeding to link.")
                 # Update label if a new one was provided? For now, we keep the existing label.
                 # If a new label was provided and differs, maybe inform the user?
                 # new_label_provided = " ".join(extra_args) if extra_args else None
                 # if new_label_provided and new_label_provided != wallet_identity.label:
                 #     await update.message.reply_text(f"ℹ️ Wallet already exists with label '{wallet_identity.label}'. Use /wallet_relabel if needed.")


        # 7. Link wallet to portfolio (using the determined chain, which is None for Solana)
        success = await self.db.add_wallet_to_portfolio(portfolio.portfolio_id, wallet_identity.wallet_id, chain)

        # 8. Adjust chain message based on wallet type and stored chain
        if wallet_type == 'solana':
             chain_msg = "on Solana" # Implicit chain for Solana
        elif chain:
             chain_msg = f"on chain '{chain}'"
        else:
             chain_msg = "for all EVM chains" # Generic EVM link

        # 9. Send confirmation or error message
        safe_formatted_address = escape_markdown(format_address(address), version=2)
        safe_wallet_type = escape_markdown(wallet_type, version=2)
        safe_portfolio_name = escape_markdown(portfolio.name, version=2)
        safe_chain_msg = escape_markdown(chain_msg, version=2)
        # Use label from the retrieved/created wallet_identity object
        safe_label = escape_markdown(wallet_identity.label, version=2)

        if success:
            await update.message.reply_text(
                f"✅ Wallet `{safe_formatted_address}` \\(Type: {safe_wallet_type}\\) added to '{safe_portfolio_name}' {safe_chain_msg} with label '{safe_label}'\\.",
                parse_mode='MarkdownV2'
            )
        else:
            # Check if wallet identity exists but link failed (already exists)
            existing_link = await self.db.check_portfolio_wallet_link(portfolio.portfolio_id, wallet_identity.wallet_id, chain)
            if existing_link:
                 await update.message.reply_text(
                     f"ℹ️ Wallet `{safe_formatted_address}` \\(Label: '{safe_label}'\\) {safe_chain_msg} is already in portfolio '{safe_portfolio_name}'\\.",
                     parse_mode='MarkdownV2'
                 )
            else:
                 # Generic failure if link doesn't exist but add failed
                 logger.error(f"Failed to add wallet {wallet_identity.wallet_id} to portfolio {portfolio.portfolio_id} for unknown reason.")
                 await update.message.reply_text(
                     f"❌ Failed to add wallet `{safe_formatted_address}` to portfolio '{safe_portfolio_name}'\\. An internal error occurred\\.",
                     parse_mode='MarkdownV2'
                 )

    def _parse_chain_and_label(self, extra_args: List[str]) -> Tuple[Optional[str], Optional[str]]:
        """
        Takes a list of extra args and returns (chain, label).
        Assumes this is called ONLY for wallet types where chain is relevant (e.g., EVM).
        """
        if not extra_args:
            return None, None # No chain, no label provided

        candidate = extra_args[0]
        normalized = normalize_chain_name(candidate)
        # Simple check: single word, reasonable length, not an address
        # TODO: Refine chain detection (e.g., check against known list from Mobula/Config?)
        is_chain = (
            len(candidate.split()) == 1 and
            len(normalized) < 20 and
            not normalized.startswith("0x") and
            normalized not in ['wallet', 'label', 'my', 'main'] # Avoid common label words
        )

        if is_chain:
            chain = normalized
            label_parts = extra_args[1:]
            label = " ".join(label_parts) if label_parts else None
        else:
            chain = None # First arg is not a chain, assume it's part of the label
            label_parts = extra_args
            label = " ".join(label_parts)

        return chain, label

    # Renamed from portfolio_removewallet
    async def portfolio_remove_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        /portfolio_remove_wallet <PortfolioName> <Address|Label> [Chain]
        Chain is optional. If omitted, removes the generic (all chains) link.
        For Solana wallets, Chain is ignored.
        """
        user_id = update.effective_user.id
        args = context.args

        if len(args) < 2 or len(args) > 3:
            await update.message.reply_text(
                "Usage: /portfolio_remove_wallet <PortfolioName> <Address|Label> [Chain]\n"
                "Example (EVM specific chain): `/portfolio_remove_wallet MyStuff 0x123...abc base`\n"
                "Example (EVM generic link): `/portfolio_remove_wallet MyStuff MyEVMLabel`\n"
                "Example (Solana): `/portfolio_remove_wallet SolStuff 6EXX...QLMG` (Chain ignored)"
            )
            return

        portfolio_name = args[0]
        wallet_identifier = args[1]
        user_provided_chain = normalize_chain_name(args[2]) if len(args) == 3 else None

        logger.info(f"User {user_id} attempting remove wallet '{wallet_identifier}' (Chain provided: {user_provided_chain or 'None'}) from '{portfolio_name}'")

        portfolio = await self.db.get_portfolio_by_name(user_id, portfolio_name)
        if not portfolio:
            safe_portfolio_name = escape_markdown(portfolio_name, version=2)
            await update.message.reply_text(f"❌ Portfolio '{safe_portfolio_name}' not found\\.", parse_mode='MarkdownV2')
            return

        wallet_identity = await self.db.find_user_wallet(user_id, wallet_identifier)
        if not wallet_identity:
            safe_identifier = escape_markdown(wallet_identifier, version=2)
            await update.message.reply_text(
                f"❌ Wallet identity '{safe_identifier}' not found\\. Use `/wallet_list` to check\\.", parse_mode='MarkdownV2'
            )
            return

        # Determine the chain to use for removal based on wallet type
        chain_to_remove: Optional[str] = None
        if wallet_identity.wallet_type == 'solana':
            chain_to_remove = None # Solana links always have chain=None in DB
            logger.info("Solana wallet detected, ignoring provided chain for removal. Using chain=None.")
        else:
            # For EVM (and others), use the provided chain (or None if not provided)
            chain_to_remove = user_provided_chain
            logger.info(f"Non-Solana wallet. Using provided chain for removal: {chain_to_remove or 'None (Generic)'}")

        # Perform removal using the determined chain
        success = await self.db.remove_wallet_from_portfolio(portfolio.portfolio_id, wallet_identity.wallet_id, chain_to_remove)

        # Adjust chain message for confirmation
        if wallet_identity.wallet_type == 'solana':
             chain_msg = "on Solana"
        elif chain_to_remove:
             chain_msg = f"on chain '{chain_to_remove}'"
        else:
             chain_msg = "generic link" # For EVM without specific chain

        safe_formatted_address = escape_markdown(format_address(wallet_identity.address), version=2)
        safe_label = escape_markdown(wallet_identity.label, version=2)
        safe_chain_msg = escape_markdown(chain_msg, version=2)
        safe_portfolio_name = escape_markdown(portfolio.name, version=2)

        if success:
            await update.message.reply_text(
                f"➖ Wallet `{safe_formatted_address}` \\(Label: '{safe_label}'\\) {safe_chain_msg} removed from '{safe_portfolio_name}'\\.",
                parse_mode='MarkdownV2'
            )
        else:
            await update.message.reply_text(
                f"❌ Wallet `{safe_formatted_address}` \\(Label: '{safe_label}'\\) {safe_chain_msg} not found in '{safe_portfolio_name}' or removal failed\\.",
                parse_mode='MarkdownV2'
            )

    async def _fetch_portfolio_data(self, portfolio_name: str, associations: List[Any]) -> Optional[List[Dict]]:
        """
        Groups wallets by type and fetches raw data from the API.
        Handles chain filtering based on associations.
        """
        wallets_by_type_and_chain = defaultdict(lambda: defaultdict(set))
        all_wallets = set()

        for assoc in associations:
            wallet = assoc.wallet
            if not wallet or not wallet.address or not wallet.wallet_type:
                logger.warning(f"Skipping association ID {assoc.association_id} for portfolio '{portfolio_name}' due to missing wallet data.")
                continue

            # Use assoc.chain (which can be None)
            chain_key = assoc.chain if assoc.chain else "generic"
            wallets_by_type_and_chain[wallet.wallet_type][chain_key].add(wallet.address)
            all_wallets.add(wallet.address)

        if not wallets_by_type_and_chain:
             logger.warning(f"Portfolio '{portfolio_name}' has associations but no valid wallets could be grouped.")
             return None

        # Create API tasks based on wallet type
        tasks = []
        for wallet_type, chain_data in wallets_by_type_and_chain.items():
            # Aggregate all unique wallets for this type first
            unique_wallets_for_type = set()
            for chain_key, wallet_set in chain_data.items():
                unique_wallets_for_type.update(wallet_set)

            if not unique_wallets_for_type:
                continue

            if wallet_type == 'solana':
                # Workaround: Call API individually for each Solana wallet due to potential API issues
                logger.info(f"Creating individual API tasks for {len(unique_wallets_for_type)} Solana wallets in portfolio '{portfolio_name}'.")
                for sol_wallet in unique_wallets_for_type:
                    tasks.append(self.portfolio_fetcher.fetch_mobula_portfolio_data(wallets=[sol_wallet])) # Pass as list
            elif wallet_type == 'evm':
                # Batch EVM wallets in one call
                wallet_list = list(unique_wallets_for_type)
                logger.info(f"Creating single API task for {len(wallet_list)} EVM wallets in portfolio '{portfolio_name}'.")
                tasks.append(self.portfolio_fetcher.fetch_mobula_portfolio_data(wallets=wallet_list))
            else:
                logger.warning(f"Unsupported wallet type '{wallet_type}' encountered during task creation for portfolio '{portfolio_name}'. Skipping.")

        if not tasks:
             logger.error(f"Logic error: No tasks created for portfolio '{portfolio_name}' despite having grouped wallets.")
             return None # Indicate failure

        # Run API calls concurrently and collect results/exceptions
        logger.info(f"Gathering results for {len(tasks)} API tasks for portfolio '{portfolio_name}'.")
        results = await asyncio.gather(*tasks, return_exceptions=True)

        api_results = []
        has_errors = False
        for i, res in enumerate(results):
            # TODO: Map result back to wallet_type/address for more specific error logging if needed
            if isinstance(res, Exception):
                # Log the exception, potentially including which wallet(s) it was for if possible
                logger.error(f"API call task failed for portfolio '{portfolio_name}': {res}")
                has_errors = True
            elif res is not None:
                # Add the successful result package to the list
                api_results.append(res)
            else:
                # Log if a task completed but returned None (might indicate no assets found for that wallet)
                logger.warning(f"API call task for portfolio '{portfolio_name}' completed but returned None.")
                # Don't treat this as a hard error unless all tasks return None

        if not api_results and has_errors:
            logger.warning(f"All API calls failed or returned None for portfolio '{portfolio_name}'.")
            return None # Indicate complete failure
        elif not api_results:
             logger.warning(f"No data returned from any API calls for portfolio '{portfolio_name}', though no exceptions occurred.")
             return [] # Return empty list to indicate no data found
        else:
            if has_errors:
                 logger.warning(f"Some API calls failed for portfolio '{portfolio_name}', but partial data was retrieved.")
            # Return the list of successfully retrieved data packages
            return api_results


    async def _analyze_portfolio_data(self, portfolio_name: str, api_results: List[Dict]) -> Optional[str]:
        """
        Analyzes the raw API data using PortfolioAnalyzer.
        TODO: Needs refactoring to handle chain filtering based on associations.
        """
        # Current implementation assumes api_results contains pre-filtered data.
        # This needs adjustment if _fetch_portfolio_data changes significantly.
        if not api_results:
             logger.warning(f"No API results provided for analysis of portfolio '{portfolio_name}'.")
             # Return a message indicating no data found, consistent with fetcher returning empty list
             safe_portfolio_name = escape_markdown(portfolio_name, version=2)
             return f"ℹ️ No holdings data found for the wallets in portfolio '{safe_portfolio_name}'\\."

        # For now, pass all results to the analyzer. It aggregates across all chains found.
        # The chain filtering logic based on specific portfolio-wallet-chain links
        # needs to be implemented either here or within the analyzer itself.
        try:
            # Assuming analyzer takes a list of data packages
            formatted_message = await self.portfolio_analyzer.analyze_and_format_holdings(portfolio_name, api_results)
            return formatted_message
        except Exception as e:
            logger.exception(f"Error during portfolio analysis for '{portfolio_name}': {e}")
            return None # Indicate analysis failure

    async def portfolio_holdings(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles the /portfolio_holdings command by orchestrating fetch and analysis.
        Expected format: /portfolio_holdings <PortfolioName>
        """
        user_id = update.effective_user.id
        args = context.args

        if not args:
            await update.message.reply_text("Usage: /portfolio_holdings <PortfolioName>")
            return

        portfolio_name = args[0]
        safe_portfolio_name_req = escape_markdown(portfolio_name, version=2) # For user messages
        logger.info(f"User {user_id} requested holdings for portfolio '{portfolio_name}'")

        # 1. Find the portfolio
        portfolio = await self.db.get_portfolio_by_name(user_id, portfolio_name)
        if not portfolio:
            logger.warning(f"Portfolio '{portfolio_name}' not found for user {user_id}.")
            await update.message.reply_text(f"❌ Portfolio named '{safe_portfolio_name_req}' not found\\.", parse_mode='MarkdownV2')
            return

        # 2. Get wallet associations
        associations = await self.db.get_portfolio_wallet_associations(portfolio.portfolio_id)
        if not associations:
            logger.info(f"Portfolio '{portfolio_name}' has no wallets associated.")
            await update.message.reply_text(f" Portfolio '{safe_portfolio_name_req}' has no wallets added yet\\. Use `/portfolio_add_wallet`\\.", parse_mode='MarkdownV2')
            return

        # 3. Fetch Data (using helper method)
        await update.message.reply_text(f"⏳ Fetching holdings data for portfolio '{safe_portfolio_name_req}'\\.\\.\\.", parse_mode='MarkdownV2')
        # Pass associations to fetcher if needed later for context, but API call uses unique wallets
        api_results = await self._fetch_portfolio_data(portfolio_name, associations)

        # Handle fetching errors/no data
        if api_results is None:
            await update.message.reply_text(f"❌ Failed to fetch holdings data for portfolio '{safe_portfolio_name_req}'\\. Check logs or try again later\\.", parse_mode='MarkdownV2')
            return
        # Note: _analyze_portfolio_data now handles the empty list case
        # if not api_results: # Empty list means API returned no data
        #      await update.message.reply_text(f"ℹ️ No holdings data found for the wallets in portfolio '{safe_portfolio_name_req}'.")
        #      return

        # 4. Analyze Data (using helper method)
        # Pass associations if analyzer needs them for filtering
        # await update.message.reply_text(f"✅ Data fetched. Analyzing holdings for '{safe_portfolio_name_req}'...") # Removed redundant message
        formatted_message = await self._analyze_portfolio_data(portfolio_name, api_results) # Pass associations here if needed

        # Handle analysis errors or no data message from analyzer
        if formatted_message is None:
            await update.message.reply_text(f"❌ An error occurred while analyzing the portfolio data\\. Please check logs\\.", parse_mode='MarkdownV2')
            return

        # 5. Send the result (formatted_message might be an info message or the actual holdings)
        await self.notifier.send_message(user_id, formatted_message, parse_mode='MarkdownV2')

    # TODO: Add other command handlers here
    # async def wallet_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: ...
    # async def summary(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: ...
    # ... and so on for all planned commands
