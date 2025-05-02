import matplotlib.pyplot as plt
import json
from collections import defaultdict
import os
# Sample data from the API response
data = {
    'total_networth_usd': '1597.79',
    'chains': [
        {
            'chain': 'arbitrum',
            'native_balance': '3857408321953902',
            'native_balance_formatted': '0.003857408321953902',
            'native_balance_usd': '7.01',
            'token_balance_usd': '4.09',
            'networth_usd': '11.10'
        },
        {
            'chain': 'avalanche',
            'native_balance': '0',
            'native_balance_formatted': '0',
            'native_balance_usd': '0.00',
            'token_balance_usd': '0.00',
            'networth_usd': '0.00'
        },
        {
            'chain': 'eth',
            'native_balance': '98085533981382099',
            'native_balance_formatted': '0.098085533981382099',
            'native_balance_usd': '178.28',
            'token_balance_usd': '335.25',
            'networth_usd': '513.52'
        },
        {
            'chain': 'linea',
            'native_balance': '4540536818619989',
            'native_balance_formatted': '0.004540536818619989',
            'native_balance_usd': '8.25',
            'token_balance_usd': '352.40',
            'networth_usd': '360.65'
        },
        {
            'chain': 'bsc',
            'native_balance': '4118551804386036',
            'native_balance_formatted': '0.004118551804386036',
            'native_balance_usd': '2.48',
            'token_balance_usd': '232.52',
            'networth_usd': '235.00'
        },
        {
            'chain': 'base',
            'native_balance': '83016370774773666',
            'native_balance_formatted': '0.083016370774773666',
            'native_balance_usd': '150.87',
            'token_balance_usd': '326.66',
            'networth_usd': '477.52'
        }
    ]
}

# Create HTML template with embedded plot and token list
html_template = """
<!DOCTYPE html>
<html>
<head>
    <title>Portfolio Distribution</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            display: flex;
            gap: 20px;
            max-width: 1200px;
            margin: 0 auto;
        }}
        .chart-container {{
            flex: 1;
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .list-container {{
            flex: 1;
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .token-list {{
            list-style-type: none;
            padding: 0;
        }}
        .token-list li {{
            padding: 10px;
            border-bottom: 1px solid #eee;
            display: flex;
            justify-content: space-between;
        }}
        .token-list li:last-child {{
            border-bottom: none;
        }}
        h2 {{
            color: #333;
            margin-top: 0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="chart-container">
            <h2>Portfolio Distribution by Blockchain</h2>
            <img src="portfolio_pie.png" alt="Portfolio Distribution" style="width: 100%;">
        </div>
        <div class="list-container">
            <h2>Token Rankings</h2>
            <ul class="token-list">
                {token_list}
            </ul>
        </div>
    </div>
</body>
</html>
"""

# Process data
chain_totals = defaultdict(float)
token_values = []

# Process chains data
chains = data.get('chains', [])
for chain_data in chains:
    chain = chain_data['chain'].upper()
    networth = float(chain_data['networth_usd'])
    chain_totals[chain] = networth
    
    # Add native token to the list
    native_value = float(chain_data['native_balance_usd'])
    if native_value > 0:
        token_values.append((f"Native {chain}", chain, native_value))
    
    # Add other tokens
    token_value = float(chain_data['token_balance_usd'])
    if token_value > 0:
        token_values.append((f"Tokens {chain}", chain, token_value))

# Remove chains with zero value
chain_totals = {k: v for k, v in chain_totals.items() if v > 0}

# Create pie chart
# Create pie chart
plt.figure(figsize=(10, 10))
plt.pie(chain_totals.values(), 
        labels=[f"{chain}\n(${value:,.2f})" for chain, value in chain_totals.items()],
        autopct='%1.1f%%',
        startangle=90)
plt.title(f'Portfolio Distribution by Blockchain\nTotal: ${float(data["total_networth_usd"]):,.2f}')
plt.savefig('portfolio_pie.png')
plt.close()

# Sort token values by USD value
token_values.sort(key=lambda x: x[2], reverse=True)

# Create token list HTML
token_list_html = ""
for token, chain, value in token_values:
    token_list_html += f'<li><span>{token} ({chain})</span><span>${value:,.2f}</span></li>'

# Generate final HTML
html_content = html_template.format(token_list=token_list_html)

# Save HTML file
with open('portfolio_distribution.html', 'w') as f:
    f.write(html_content)

print("Portfolio visualization has been created. Open portfolio_distribution.html to view the results.")
