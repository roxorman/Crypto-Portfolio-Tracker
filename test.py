import requests
import os
import json
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv('COINMARKETCAP_API_KEY')

url = 'https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest'
params = {
    'slug': 'messier',
    'convert': 'USD'
}

headers = {
    'X-CMC_PRO_API_KEY': api_key,
}

response = requests.get(url, headers=headers, params=params)
data = response.json()


print(json.dumps(data, indent=4))