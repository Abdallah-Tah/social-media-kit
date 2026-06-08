#!/usr/bin/env python3
"""DEBUG ONLY — DO NOT USE IN PRODUCTION — DO NOT STORE REAL TOKENS HERE.

Archived troubleshooting script kept for historical reference. Use the supported
LinkedIn poster scripts with environment variables instead of editing tokens into
source files.
"""
import requests
import json
import os

# Read token from file
import os
ACCESS_TOKEN = os.environ.get('LINKEDIN_ACCESS_TOKEN', '')

print(f'Token length: {len(ACCESS_TOKEN)}')
print(f'Token starts with: {ACCESS_TOKEN[:10]}')

headers = {
    'Authorization': 'Bearer <TOKEN_FROM_ENV>',
    'Content-Type': 'application/json',
    'X-Restli-Protocol-Version': '2.0.0'
}

# Test the token
resp = requests.get('https://api.linkedin.com/v2/me', headers=headers)
print(f'Profile request status: {resp.status_code}')
print(resp.text[:300])

# Try to get organizations
resp2 = requests.get('https://api.linkedin.com/v2/organizations/119694084', headers=headers)
print(f'\nOrganization request status: {resp2.status_code}')
print(resp2.text[:300])

# Register upload for image
register_url = 'https://api.linkedin.com/v2/assets?action=registerUpload'
register_payload = {
    'registerUploadRequest': {
        'recipes': ['urn:li:digitalmediaRecipe:feedshare-image'],
        'owner': 'urn:li:organization:119694084',
        'serviceRelationships': [
            {
                'relationshipType': 'OWNER',
                'identifier': 'urn:li:userGeneratedContent'
            }
        ]
    }
}

resp3 = requests.post(register_url, json=register_payload, headers=headers)
print(f'\nRegister upload status: {resp3.status_code}')
print(resp3.text[:500])

if resp3.status_code == 200:
    result = resp3.json()
    upload_url = result['value']['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
    asset_urn = result['value']['asset']
    
    # Upload the image
    image_path = '<LOCAL_IMAGE_PATH>'
    with open(image_path, 'rb') as img:
        upload_resp = requests.post(upload_url, data=img, headers={
            'Authorization': 'Bearer <TOKEN_FROM_ENV>',
            'Content-Type': 'image/png'
        })
    print(f'Image upload status: {upload_resp.status_code}')
    
    # Create the post with image
    post_url = 'https://api.linkedin.com/v2/ugcPosts'
    post_payload = {
        'author': 'urn:li:organization:119694084',
        'lifecycleState': 'PUBLISHED',
        'specificContent': {
            'com.linkedin.ugc.ShareContent': {
                'shareCommentary': {
                    'text': '🚀 New Tutorial: Build Your First MCP Server\n\nMCP (Model Context Protocol) lets you connect Claude to your REAL data — databases, APIs, files — in 15 minutes with Python.\n\n✅ Build a Python MCP server\n✅ Connect to SQLite\n✅ Ask natural-language questions\n✅ Deploy to Claude Desktop\n\n🔗 https://buildwithabdallah.com/tutorials/build-your-first-mcp-server\n\n#AI #MCP #Python #Claude #BuildWithAbdallah'
                },
                'shareMediaCategory': 'IMAGE',
                'media': [
                    {
                        'status': 'READY',
                        'description': {
                            'text': 'MCP Server Tutorial'
                        },
                        'media': asset_urn,
                        'title': {
                            'text': 'Build Your First MCP Server'
                        }
                    }
                ]
            }
        },
        'visibility': {
            'com.linkedin.ugc.MemberNetworkVisibility': 'PUBLIC'
        }
    }
    
    post_resp = requests.post(post_url, json=post_payload, headers=headers)
    print(f'\nPost creation status: {post_resp.status_code}')
    print(f'Response: {post_resp.text}')
    
    if post_resp.status_code == 201:
        print('\n✅ Successfully posted to LinkedIn!')
    else:
        print('\n❌ Failed to post')
else:
    print('Failed to register upload')
