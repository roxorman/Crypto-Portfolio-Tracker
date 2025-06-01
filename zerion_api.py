import requests
import os
import json
from datetime import datetime

url = "https://api.zerion.io/v1/wallets/0x5d39036947e83862ce5f3db351cc64e3d4592cd5/charts/max?currency=usd"

headers = {
    "accept": "application/json",
    "authorization": "Basic emtfZGV2X2NhNmUwYmFlNDJhOTQ1ZTZiOThmYjA0NTQ5MmI1ZWYyOg=="
}


response = requests.get(url, headers=headers)

# print json response
data = response.json()


import matplotlib.pyplot as plt
import matplotlib.dates as mdates

if response.status_code == 200 and 'data' in data and 'attributes' in data['data'] and 'points' in data['data']['attributes']:
    points = data['data']['attributes']['points']
    
    # Extract timestamps and values
    timestamps = [point[0] for point in points]
    values = [point[1] for point in points]
    
    # Convert timestamps to datetime objects
    dates = [datetime.fromtimestamp(ts) for ts in timestamps]
    
    # Create the plot
    plt.figure(figsize=(10, 6))
    plt.plot(dates, values, marker='o', linestyle='-')
    
    # Format the x-axis to show dates nicely
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.gca().xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.gcf().autofmt_xdate() # Rotate date labels
    
    plt.title('Wallet Value Over Time')
    plt.xlabel('Date')
    plt.ylabel('Value (USD)')
    plt.grid(True)
    plt.tight_layout() # Adjust layout to prevent labels from overlapping
    plt.show()
else:
    print("Could not retrieve data for plotting or data format is incorrect.")
