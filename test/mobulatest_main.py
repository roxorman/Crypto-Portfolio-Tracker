import requests
import os
from dotenv import load_dotenv
from typing import Dict, List, Optional
import json

load_dotenv()
MOBULA_API_KEY = os.getenv("MOBULA_API_KEY")

def get_wallet_portfolio(wallet_address):
    url = "https://api.mobula.io/api/1/wallet/portfolio"
    headers = {"Authorization": f"Bearer {MOBULA_API_KEY}"}
    params = {
                "wallets": wallet_address,
                "filterSpam": "true",
                "liqmin": "1000",
                "unlistedAssets": "false",
                "pnl": "false",
                "cache": "true",
                "blockchain": "",
            }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        # remove tokens with value less than 1 USD
        data = response.json()
        if data.get('data'):
            data['data']['assets'] = [asset for asset in data['data']['assets'] if float(asset.get('estimated_balance', 0)) >= 1]
            data['data']['balances_length'] = len(data['data']['assets'])
        else:
            print(f"No data found for wallet {wallet_address}")
            return None
        return data
    except requests.exceptions.RequestException as e:
        print(f"API Error: {e}")
        return None

# Example usage
portfolio_data = get_wallet_portfolio("0xCe100d94EA22aAb119633D434BdEEA26F4244d1a,0x5D39036947e83862cE5f3DB351cC64E3D4592cD5")


total_value = portfolio_data['data'].get('total_wallet_balance', 0)

# Save the JSON response to a file and if it exists the rewrite it
with open("portfolio_data2.json", "w") as json_file:
    json.dump(portfolio_data, json_file, indent=4)

print(json.dumps(portfolio_data, indent=4))
