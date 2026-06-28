import requests

TOKEN = "cfoat_OI5oLaHDpenSoUbvX_6QfPnqUiGArrr2bssME3OFD5Q.OBLgPPliRc1sijK-nfP4d_aSjVNWqnJVZ2tCIt8L738"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
ZONE_ID = "45697116b8d209b6f255ed8d2d35e815"

# List all DNS records
print("=== Current DNS Records ===")
r = requests.get(f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/dns_records", headers=HEADERS)
data = r.json()

if data.get("result"):
    for rec in data["result"]:
        print(f"  {rec['type']:6} {rec['name']:40} -> {rec['content']:30} proxied={rec['proxied']}")
else:
    print(f"  No result or error: {data}")

# Check if server.favoriteweb.net exists
server_record = [r for r in data.get("result", []) if r["name"] == "server.favoriteweb.net"]
if not server_record:
    print("\n=== Adding CNAME for server.favoriteweb.net ===")
    dns_data = {
        "type": "CNAME",
        "name": "server",
        "content": "khan.favoriteweb.net",
        "ttl": 1,
        "proxied": True
    }
    r2 = requests.post(
        f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/dns_records",
        headers=HEADERS,
        json=dns_data
    )
    if r2.json().get("success"):
        print("✅ DNS record added successfully!")
    else:
        print(f"❌ Failed: {r2.json()}")
else:
    rec = server_record[0]
    print(f"\n=== server.favoriteweb.net already exists ===")
    print(f"  Type: {rec['type']}")
    print(f"  Content: {rec['content']}")
    print(f"  Proxied: {rec['proxied']}")

# Show worker routes
print("\n=== Worker Routes ===")
r4 = requests.get(
    f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/workers/routes",
    headers=HEADERS
)
for route in r4.json().get("result", []):
    print(f"  {route['pattern']:40} -> {route.get('script', 'N/A')}")

print("\n✅ Setup verification complete!")