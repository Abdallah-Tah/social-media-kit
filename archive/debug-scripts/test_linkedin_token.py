#!/usr/bin/env python3
"""DEBUG ONLY — DO NOT USE IN PRODUCTION — DO NOT STORE REAL TOKENS HERE.

Archived troubleshooting script kept for historical reference. Use the supported
LinkedIn poster scripts with environment variables instead of editing tokens into
source files.
"""
import requests
import json

# Full access token from the JSON response
ACCESS_TOKEN = '<PASTE_TOKEN_IN_ENV_NOT_SOURCE>'

headers = {
    'Authorization': 'Bearer <TOKEN_FROM_ENV>',
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
