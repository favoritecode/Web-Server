import requests
import json
import subprocess
import re
import os

# First get the Cloudflare API token from wrangler
# We'll use the CF_API_TOKEN env var or prompt
print("=" * 60)
print("Setting up server.favoriteweb.net failover worker")
print("=" * 60)

# Get zone ID for favoriteweb.net
ACCOUNT_ID = "3ccb6d9d09cd8f403fcfc51804f78519"

# Try to get OAuth token from wrangler config
wrangler_config_path = os.path.expanduser("~\\AppData\\Roaming\\xdg.config\\.wrangler\\default.toml")
try:
    with open(wrangler_config_path, 'r') as f:
        config = f.read()
    # Extract oauth_token
    match = re.search(r'oauth_token\s*=\s*["\']([^"\']+)["\']', config)
    if match:
        api_token = match.group(1)
        print(f"Found OAuth token from wrangler config")
    else:
        print("No OAuth token found in wrangler config")
        api_token = None
except:
    print("Could not read wrangler config")
    api_token = None

if not api_token:
    print("\nPlease provide a Cloudflare API Token with Workers and Zone permissions:")
    print("Or run: npx wrangler login")
    exit(1)

HEADERS = {
    "Authorization": f"Bearer {api_token}",
    "Content-Type": "application/json"
}

# 1. Find zone ID for favoriteweb.net
print("\n1. Finding zone ID for favoriteweb.net...")
r = requests.get(
    f"https://api.cloudflare.com/client/v4/zones",
    headers=HEADERS,
    params={"name": "favoriteweb.net"}
)
if r.status_code == 200 and r.json().get("success"):
    zones = r.json()["result"]
    if zones:
        ZONE_ID = zones[0]["id"]
        print(f"   Zone ID: {ZONE_ID}")
    else:
        print("   Zone not found! Checking all zones...")
        r2 = requests.get(
            f"https://api.cloudflare.com/client/v4/zones",
            headers=HEADERS
        )
        for z in r2.json().get("result", []):
            print(f"   - {z['name']}: {z['id']}")
        exit(1)
else:
    print(f"   Error: {r.text}")
    exit(1)

# 2. Add route for server.favoriteweb.net to our worker
print("\n2. Adding route server.favoriteweb.net -> server-failover worker...")
route_data = {
    "pattern": "server.favoriteweb.net/*",
    "script": "server-failover"
}
r = requests.post(
    f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/workers/routes",
    headers=HEADERS,
    json=route_data
)
if r.status_code == 200 and r.json().get("success"):
    print("   ✅ Route added successfully!")
else:
    print(f"   Response: {r.text}")
    # Route might already exist, try getting existing routes
    print("   Checking existing routes...")
    r2 = requests.get(
        f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/workers/routes",
        headers=HEADERS
    )
    if r2.status_code == 200:
        routes = r2.json().get("result", [])
        for route in routes:
            print(f"   - {route['pattern']} -> {route.get('script', 'N/A')}")

# 3. Also add a DNS record for server.favoriteweb.net
print("\n3. Checking DNS for server.favoriteweb.net...")
r = requests.get(
    f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/dns_records",
    headers=HEADERS,
    params={"name": "server.favoriteweb.net", "type": "CNAME"}
)
if r.status_code == 200:
    records = r.json().get("result", [])
    if not records:
        print("   No DNS record found. Adding CNAME...")
        dns_data = {
            "type": "CNAME",
            "name": "server",
            "content": "khan.favoriteweb.net",  # Worker will handle failover
            "ttl": 1,
            "proxied": True
        }
        r3 = requests.post(
            f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/dns_records",
            headers=HEADERS,
            json=dns_data
        )
        if r3.status_code == 200 and r3.json().get("success"):
            print("   ✅ DNS record added!")
        else:
            print(f"   Error: {r3.text}")
    else:
        print(f"   DNS record exists: {records[0]['name']} -> {records[0]['content']}")
        # Update to proxied if needed
        if not records[0]['proxied']:
            dns_data = records[0]
            dns_data['proxied'] = True
            r4 = requests.put(
                f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/dns_records/{records[0]['id']}",
                headers=HEADERS,
                json=dns_data
            )
            if r4.status_code == 200:
                print("   ✅ DNS updated to proxied (orange cloud)!")

# 4. Test the worker
print("\n4. Worker status:")
r = requests.get(
    f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/workers/scripts/server-failover",
    headers=HEADERS
)
if r.status_code == 200:
    worker_info = r.json().get("result", {})
    print(f"   Script: {worker_info.get('id', 'N/A')}")
    print(f"   Tag: {worker_info.get('etag', 'N/A')[:20]}...")
    print("\n   ✅ Worker server-failover is deployed!")

print("\n" + "=" * 60)
print("Setup complete! Waiting for DNS propagation...")
print("Try: curl https://server.favoriteweb.net")
print("=" * 60)