import requests
import os
import json

url = "https://api.zerion.io/v1/wallets/0x5d39036947e83862ce5f3db351cc64e3d4592cd5/portfolio"

headers = {
    "accept": "application/json",
    "authorization": "Basic emtfZGV2X2NhNmUwYmFlNDJhOTQ1ZTZiOThmYjA0NTQ5MmI1ZWYyOg=="
}


response = requests.get(url, headers=headers)

# print json response
data = response.json()

print(json.dumps(data, indent=4))