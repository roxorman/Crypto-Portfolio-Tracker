import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

MOBULA_API_KEY = os.getenv("MOBULA_API_KEY")

def get_wallet_portfolio(wallet_address):
    url = "https://api.mobula.io/api/1/wallet/portfolio"
    headers = {"Authorization": f"Bearer {MOBULA_API_KEY}"}
    params = {"wallet": wallet_address}
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"API Error: {e}")
        return None

# Example usage
portfolio_data = get_wallet_portfolio("0xCe100d94EA22aAb119633D434BdEEA26F4244d1a")


total_value = portfolio_data['data'].get('total_wallet_balance', 0)
print(f"Total Wallet Value: {total_value} USD")
