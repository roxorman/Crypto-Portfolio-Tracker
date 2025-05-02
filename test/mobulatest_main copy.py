from sql import PortfolioDatabase
from typing import Dict, List
import json
from datetime import datetime

class PortfolioTracker:
    """Portfolio tracking using Mobula API with SQL database integration."""
    
    def __init__(self):
        self.db = PortfolioDatabase()

    def setup_test_data(self):
        """Create test user and portfolio with sample wallets."""
        # Create user
        user_id = self.db.add_user("testuser")
        
        # Create portfolio
        portfolio_id = self.db.create_portfolio(
            user_id, 
            "Main Portfolio", 
            "Primary investment portfolio"
        )
        
        # Add test wallets
        wallets = [
            ("0xCe100d94EA22aAb119633D434BdEEA26F4244d1a", "ethereum", "Main ETH"),
            ("0x1E6E8695FAb3Eb382534915eA8d7Cc1D1994B152", "ethereum", "Secondary ETH"),
            ("6EXXKyEz5ZWNPzi1jdv3GJ86WjYC6uYRoCAz9YMYQLMG", "solana", "Main SOL")
        ]
        
        for address, chain, label in wallets:
            self.db.add_wallet(portfolio_id, address, chain, label)
            
        return user_id, portfolio_id

    def get_user_portfolios(self, user_id: int) -> List[Dict]:
        """Get all portfolios and their wallets for a user."""
        try:
            # Get user's portfolios
            portfolios = []
            
            # Query for portfolios by user_id
            self.db.cursor.execute("""
                SELECT portfolio_id, name, description 
                FROM portfolios 
                WHERE user_id = ?
            """, (user_id,))
            
            portfolio_rows = self.db.cursor.fetchall()
            
            for p_row in portfolio_rows:
                portfolio_id, name, description = p_row
                
                # Get wallets for this portfolio
                wallets = self.db.get_portfolio_wallets(portfolio_id)
                
                portfolios.append({
                    'portfolio_id': portfolio_id,
                    'name': name,
                    'description': description,
                    'wallets': wallets
                })
                
            return portfolios
            
        except Exception as e:
            print(f"Error getting user portfolios: {e}")
            return []

    def update_portfolio_holdings(self, portfolio_id: int) -> Dict:
        """Update and return holdings for all wallets in a portfolio."""
        try:
            # Get all wallets in portfolio
            wallets = self.db.get_portfolio_wallets(portfolio_id)
            portfolio_data = {
                'total_value': 0,
                'wallets': {}
            }
            
            for wallet in wallets:
                # Get holdings from Mobula API
                holdings = self.db.get_wallet_holdings(wallet['address'])
                
                if holdings and holdings.get('data'):
                    # Update wallet in database
                    self.db.update_wallet_value(wallet['wallet_id'], holdings)
                    
                    # Add to portfolio data
                    wallet_value = holdings['data'].get('total_wallet_balance', 0)
                    portfolio_data['total_value'] += wallet_value
                    portfolio_data['wallets'][wallet['address']] = {
                        'label': wallet['label'],
                        'chain': wallet['chain'],
                        'value': wallet_value,
                        'holdings': holdings['data'].get('assets', [])
                    }
            
            # Update total portfolio value
            self.db.update_portfolio_value(portfolio_id)
            
            return portfolio_data
            
        except Exception as e:
            print(f"Error updating portfolio holdings: {e}")
            return None

    def format_holdings_summary(self, portfolio_data: Dict) -> str:
        """Format portfolio holdings into readable summary."""
        summary = ["📊 Portfolio Summary"]
        summary.append(f"\n💰 Total Value: ${portfolio_data['total_value']:,.2f}")
        
        for address, wallet_data in portfolio_data['wallets'].items():
            summary.append(f"\n\n👛 {wallet_data['label']} ({address[:6]}...{address[-4:]})")
            summary.append(f"Chain: {wallet_data['chain']}")
            summary.append(f"Value: ${wallet_data['value']:,.2f}")
            
            if wallet_data['holdings']:
                summary.append("\nHoldings:")
                for token in wallet_data['holdings']:
                    if token.get('estimated_balance', 0) > 1:  # Filter small balances
                        summary.append(
                            f"  • {token['asset']['name']} ({token['asset']['symbol']}): "
                            f"${token['estimated_balance']:,.2f}"
                        )
        
        return "\n".join(summary)

if __name__ == "__main__":
    tracker = PortfolioTracker()
    
    # Setup test data if needed
    user_id, portfolio_id = tracker.setup_test_data()
    
    # Get all user's portfolios
    portfolios = tracker.get_user_portfolios(user_id)
    
    print(f"\nFound {len(portfolios)} portfolios for user {user_id}")
    
    for portfolio in portfolios:
        print(f"\nProcessing portfolio: {portfolio['name']}")
        
        # Update and get latest holdings
        holdings = tracker.update_portfolio_holdings(portfolio['portfolio_id'])
        
        if holdings:
            # Print formatted summary
            print(tracker.format_holdings_summary(holdings))
            
            # Save raw data to file
            with open(f"portfolio_{portfolio['portfolio_id']}_data.json", 'w') as f:
                json.dump(holdings, f, indent=2)
            print(f"\nRaw data saved to portfolio_{portfolio['portfolio_id']}_data.json")
        
    tracker.db.close()
