#!/usr/bin/env python3
import requests
import json

# Access token from the database
ACCESS_TOKEN = '***'

headers = {
    'Authorization': f'***',
    'Content-Type': 'application/json',
    'X-Restli-Protocol-Version': '2.0.0'
}

# Image path
image_path = '/home/abdaltm86/.openclaw/workspace/social/content/raw/2026-06-03_mcp-server-tutorial-card.png'

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

resp = requests.post(register_url, json=register_payload, headers=headers)
print(f'Register upload status: {resp.status_code}')

if resp.status_code == 200:
    result = resp.json()
    upload_url = result['value']['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
    asset_urn = result['value']['asset']
    
    # Upload the image
    with open(image_path, 'rb') as img:
        upload_resp = requests.post(upload_url, data=img, headers={
            'Authorization': f'***',
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
    print(f'Post creation status: {post_resp.status_code}')
    print(f'Response: {post_resp.text}')
    
    if post_resp.status_code == 201:
        print('\n✅ Successfully posted to LinkedIn!')
    else:
        print('\n❌ Failed to post')
else:
    print('Failed to register upload')
    print(resp.text)
