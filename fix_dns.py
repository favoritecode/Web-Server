import requests

TOKEN = "cfoat_OI5oLaHDpenSoUbvX_6QfPnqUiGArrr2bssME3OFD5Q.OBLgPPliRc1sijK-nfP4d_aSjVNWqnJVZ2tCIt8L738"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
ZONE_ID = "45697116b8d209b6f255ed8d2d35e815"

# Get all DNS records
r = requests.get(f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/dns_records", headers=HEADERS)
data = r.json()
print(f"API Success: {data.get('success')}")
if not data.get("success"):
    print(f"Error: {data.get('errors')}")
    # Try with different token format
    print("Trying with Bearer token...")
    exit(1)

# Find server.favoriteweb.net record
for rec in data.get("result", []):
    if rec["name"] == "server.favoriteweb.net":
        print(f"\nFound server.favoriteweb.net:")
        print(f"  Type: {rec['type']}")
        print(f"  Content: {rec['content']}")
        print(f"  Proxied: {rec['proxied']}")
        print(f"  ID: {rec['id']}")
        
        # The problem: CNAME to khan.favoriteweb.net makes Cloudflare 
        # follow the CNAME directly, bypassing the Worker.
        # Solution: Change to A record with dummy IP, proxied=True
        # The Worker route will then intercept the traffic.
        
        if rec["type"] == "CNAME":
            print("\n  ❌ CNAME detected! This bypasses the Worker.")
            print("  Changing to A record with dummy IP...")
            
            update_data = {
                "type": "A",
                "name": "server",
                "content": "192.0.2.1",  # RFC 5737 TEST-NET-1, dummy IP
                "ttl": 1,
                "proxied": True
            }
            r2 = requests.put(
                f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/dns_records/{rec['id']}",
                headers=HEADERS,
                json=update_data
            )
            result = r2.json()
            if result.get("success"):
                print("  ✅ Changed to A record (proxied)! Worker will now intercept.")
            else:
                print(f"  ❌ Failed: {result}")
        else:
            print("\n  ✅ Already an A record. Make sure proxied=True")
        break
else:
    print("\nserver.favoriteweb.net not found in DNS records!")
    print("Creating new A record...")
    dns_data = {
        "type": "A",
        "name": "server",
        "content": "192.0.2.1",
        "ttl": 1,
        "proxied": True
    }
    r3 = requests.post(
        f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/dns_records",
        headers=HEADERS,
        json=dns_data
    )
    result = r3.json()
    if result.get("success"):
        print("  ✅ A record created! Worker will intercept traffic.")
    else:
        print(f"  ❌ Failed: {result}")

# Verify worker routes
print("\n=== Worker Routes ===")
r4 = requests.get(
    f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/workers/routes",
    headers=HEADERS
)
for route in r4.json().get("result", []):
    print(f"  {route['pattern']} -> {route.get('script', 'N/A')}")