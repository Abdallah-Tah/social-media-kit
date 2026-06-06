#!/usr/bin/env python3
import requests
import json

# Full access token from the JSON response
ACCESS_TOKEN = '***'

headers = {
    'Authorization': f'***',
    'Content-Type': 'application/json',
    'X-Restli-Protocol-Version': '2.0.0'
}

# Test with a simple profile request
resp = requests.get('https://api.linkedin.com/v2/me', headers=headers)
print(f'Profile request status: {resp.status_code}')
print(resp.text[:300])

# Try to get organizations
resp2 = requests.get('https://api.linkedin.com/v2/organizations/119694084', headers=headers)
print(f'\\nOrganization request status: {resp2.status_code}')
print(resp2.text[:300])
