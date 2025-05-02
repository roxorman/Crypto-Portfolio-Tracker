import requests
import os
from dotenv import load_dotenv
from typing import Dict, List, Optional
import json

class MobulaPortfolioTracker:
    """Handles portfolio tracking using Mobula API with support for multiple chains."""
    
    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv("MOBULA_API_KEY")
        self.base_url = "https://api.mobula.io/api/1"
        
        # Default settings
        self.min_token_value = 1  # Minimum USD value to include token
        self.min_liquidity = 1000   # Minimum liquidity for token filtering
        self.filter_spam = True     # Filter out spam tokens

        # Chain ID to name mapping
        self.chain_names = {
            "1": "Ethereum",
            "42161": "Arbitrum",
            "8453": "Base",
            "10": "Optimism",
            "56": "BSC",
            "137": "Polygon",
            "59144": "Linea",
            "324": "zkSync"
        }

    def get_wallet_data(self, wallet: str) -> Dict:
        """
        Get wallet data for any wallet (EVM/Solana/Sui).
        """
        try:
            url = f"{self.base_url}/wallet/portfolio"
            params = {
                "wallet": wallet,
                "filterSpam": str(self.filter_spam).lower(),
                "liqmin": str(self.min_liquidity),
                "unlistedAssets": "false",
                "pnl": "true",
            }
            headers = {
                "Authorization": self.api_key
            }

            print(f"Making request to {url}")
            print(f"Headers: {headers}")
            print(f"Params: {params}")

            response = requests.get(url, params=params, headers=headers)
            response.raise_for_status()
            result = response.json()
            
            if not result.get('data') or not result['data'].get('assets'):
                print(f"No data found for wallet {wallet}")
                return None
                
            return result
        except requests.exceptions.RequestException as e:
            print(f"Error fetching data for wallet {wallet}: {e}")
            return None

    def process_wallet_data(self, wallet: str, data: Dict) -> Dict:
        """Process raw wallet data into organized format by chain."""
        portfolio = {}
        total_value = 0
        
        if not data.get('data') or not data['data'].get('assets'):
            return None

        for asset in data['data']['assets']:
            # Process cross-chain balances
            if not asset.get('cross_chain_balances'):
                continue

            for chain_name, balance_data in asset['cross_chain_balances'].items():
                if float(balance_data['balance']) <= 0:
                    continue

                chain = chain_name
                if chain not in portfolio:
                    portfolio[chain] = {
                        'total': 0,
                        'tokens': {}
                    }

                token_name = asset['asset']['name']
                balance = float(balance_data['balance'])
                price = float(asset['price'])
                balance_usd = balance * price

                # Only add tokens worth minimum value or more
                if balance_usd >= self.min_token_value:
                    token_data = {
                        'balance': balance,
                        'balance_usd': balance_usd,
                        'price': price,
                        'symbol': asset['asset']['symbol'],
                        'address': balance_data['address']
                    }
                    portfolio[chain]['tokens'][token_name] = token_data
                    portfolio[chain]['total'] += balance_usd
                    total_value += balance_usd

        # Remove chains with zero total value
        portfolio = {k: v for k, v in portfolio.items() if v['total'] > 0}
        
        # Add total portfolio value
        if total_value > 0:
            portfolio['total_value'] = total_value
            return portfolio
        return None

    def format_portfolio_summary(self, all_wallets_data: Dict) -> str:
        """Format portfolio data as a readable string."""
        summary = ["\n=== Portfolio Summary ==="]
        total_portfolio_value = 0

        for wallet, portfolio in all_wallets_data.items():
            if not portfolio:  # Skip empty portfolios
                continue
                
            wallet_total = portfolio.get('total_value', 0)
            total_portfolio_value += wallet_total
            summary.append(f"\n📍 Wallet: {wallet[:6]}...{wallet[-4:]}")

            # Sort chains by total value
            chains = [(chain, data) for chain, data in portfolio.items() if chain != 'total_value']
            sorted_chains = sorted(chains, key=lambda x: x[1]['total'], reverse=True)

            for chain, chain_data in sorted_chains:
                if chain_data['total'] >= self.min_token_value:
                    summary.append(f"\n  🔗 {chain}: ${chain_data['total']:,.2f}")
                    
                    # Sort tokens by USD value
                    sorted_tokens = sorted(
                        chain_data['tokens'].items(),
                        key=lambda x: x[1]['balance_usd'],
                        reverse=True
                    )
                    
                    for token_name, token_data in sorted_tokens:
                        if token_data['balance_usd'] >= self.min_token_value:
                            summary.append(
                                f"    • {token_name} ({token_data['symbol']}): "
                                f"${token_data['balance_usd']:,.2f} "
                                f"({token_data['balance']:,.4f} tokens)"
                            )

            summary.append(f"\n  💰 Wallet Total: ${wallet_total:,.2f}")

        summary.append(f"\n📊 Total Portfolio Value: ${total_portfolio_value:,.2f}")
        return "\n".join(summary)

# Example usage
if __name__ == "__main__":
    tracker = MobulaPortfolioTracker()
    
    # Define wallets to track
    wallets = [
        "0xCe100d94EA22aAb119633D434BdEEA26F4244d1a",  # EVM wallet (gets all EVM chains automatically)
        "6EXXKyEz5ZWNPzi1jdv3GJ86WjYC6uYRoCAz9YMYQLMG",  # Solana wallet
        "0xb6e2acc626fcc95ee729d3eca454766d6c473c020a731248fb879f76da253183"  # Sui wallet
    ]
    
    # Get and process data for all wallets
    all_wallets_data = {}
    for wallet in wallets:
        data = tracker.get_wallet_data(wallet)
        if data:
            processed_data = tracker.process_wallet_data(wallet, data)
            if processed_data:
                all_wallets_data[wallet] = processed_data
    
    # Print detailed summary
    print(tracker.format_portfolio_summary(all_wallets_data))
    
    # Save raw data to file
    with open('portfolio_data.json', 'w') as f:
        json.dump(all_wallets_data, f, indent=2)
    print("\nRaw data saved to portfolio_data.json")
