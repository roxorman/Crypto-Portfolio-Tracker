import requests
import os
from dotenv import load_dotenv
from typing import Dict, List, Optional
import json

load_dotenv()
MOBULA_API_KEY = os.getenv("MOBULA_API_KEY")

def get_wallet_portfolio(wallet_address):
    url = "https://api.mobula.io/api/1/wallet/portfolio"
    # Example wallet addresses 
    solana1 = "DXm7q65Grad9fAkWVkVCDwt1RJX1ARkntH964cS1FdYd"
    solana2 = "6EXXKyEz5ZWNPzi1jdv3GJ86WjYC6uYRoCAz9YMYQLMG"
    solana_portfolio = solana1 + "," + solana2
    eth_wallet_addresses = "0xCe100d94EA22aAb119633D434BdEEA26F4244d1a"
    headers = {"Authorization": f"Bearer {MOBULA_API_KEY}"}
    params = {
                "wallets": eth_wallet_addresses,
                "filterSpam": "true",
                "liqmin": "1000",
                "unlistedAssets": "true",
                "pnl": "false",
                "cache": "true",
                "blockchain": "",   # Leaving blank to get all chains            
            }
    
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status() # Raises an HTTPError for bad responses (4XX or 5XX)
        data = response.json()

        # Check if the necessary data structure exists and is valid
        if data.get('data') and isinstance(data['data'].get('assets'), list):
            # Filter assets: keep only those with estimated_balance >= 1 USD
            # Use a generator expression for potentially better memory efficiency if list is huge,
            # then convert to list. For typical sizes, list comprehension is fine.
            filtered_assets = [
                asset for asset in data['data']['assets']
                if float(asset.get('estimated_balance', 0)) >= 1
            ]
            
            # Get the count of assets meeting the threshold
            count_above_threshold = len(filtered_assets)

            # Update the assets list in the data dictionary with the filtered list
            data['data']['assets'] = filtered_assets
            
            # Update the original length key to reflect the filtered count
            data['data']['balances_length'] = count_above_threshold 
            
            # Add the new key indicating the count above the threshold
            data['data']['tokens_above_minimum_threshold'] = count_above_threshold
        
        # Handle cases where 'data' key exists but 'assets' is missing or not a list
        elif data.get('data') and not isinstance(data['data'].get('assets'), list):
             print(f"Warning: 'assets' key missing or not a list in data for wallet {wallet_address}")
             # Ensure structure consistency
             data['data']['assets'] = []
             data['data']['balances_length'] = 0
             data['data']['tokens_above_minimum_threshold'] = 0
        
        # Handle case where 'data' key itself is missing
        elif not data.get('data'):
             print(f"No 'data' key found in API response for wallet {wallet_address}")
             # Return None or an empty structure based on requirements
             return None 
             # Example: return {'data': {'assets': [], 'balances_length': 0, 'tokens_above_minimum_threshold': 0}}

        return data

    except requests.exceptions.RequestException as e:
        print(f"API Request Error: {e}")
        return None
    except json.JSONDecodeError as e:
        # Log the response text that failed to parse for debugging
        print(f"JSON Decode Error: {e}. Response text: {response.text if 'response' in locals() else 'Response object not available'}")
        return None
    except (ValueError, TypeError) as e:
        # Catch potential errors during float conversion or if asset structure is unexpected
        print(f"Data processing error (ValueError/TypeError): {e}")
        return None 
    except KeyError as e:
        # Catch errors if expected keys like 'estimated_balance' are missing in an asset
        print(f"Data processing error (KeyError): Missing key {e} in asset data")
        return None

# Example usage
portfolio_data = get_wallet_portfolio("0xCe100d94EA22aAb119633D434BdEEA26F4244d1a,0x5D39036947e83862cE5f3DB351cC64E3D4592cD5")


total_value = portfolio_data['data'].get('total_wallet_balance', 0)

# Save the JSON response to a file and if it exists the rewrite it
with open("portfolio_data2.json", "w") as json_file:
    json.dump(portfolio_data, json_file, indent=4)

print(json.dumps(portfolio_data, indent=4))
