import requests

TOKEN = "cfoat_OI5oLaHDpenSoUbvX_6QfPnqUiGArrr2bssME3OFD5Q.OBLgPPliRc1sijK-nfP4d_aSjVNWqnJVZ2tCIt8L738"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# 1. Get zone ID
print("1. Getting zone ID for favoriteweb.net...")
r = requests.get("https://api.cloudflare.com/client/v4/zones", headers=HEADERS, params={"name": "favoriteweb.net"})
data = r.json()
if data.get("success") and data["result"]:
    ZONE_ID = data["result"][0]["id"]
    print(f"   Zone ID: {ZONE_ID}")
else:
    print(f"   Error: {data}")
    exit(1)

# 2. Add route
print("\n2. Adding route server.favoriteweb.net -> server-failover...")
route_data = {"pattern": "server.favoriteweb.net/*", "script": "server-failover"}
r = requests.post(f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/workers/routes", headers=HEADERS, json=route_data)
if r.status_code == 200 and r.json().get("success"):
    print("   ✅ Route added!")
else:
    print(f"   {r.json()}")

# 3. Check DNS
print("\n3. Checking DNS for server.favoriteweb.net...")
r = requests.get(f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/dns_records", headers=HEADERS, params={"name": "server.favoriteweb.net"})
records = r.json().get("result", [])
if not records:
    print("   Adding CNAME record...")
    dns = {"type": "CNAME", "name": "server", "content": "khan.favoriteweb.net", "ttl": 1, "proxied": True}
    r2 = requests.post(f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/dns_records", headers=HEADERS, json=dns)
    if r2.json().get("success"):
        print("   ✅ DNS record added!")
    else:
        print(f"   {r2.json()}")
else:
    print(f"   DNS exists: {records[0]['name']} -> {records[0]['content']} (proxied={records[0]['proxied']})")

print("\n✅ Setup complete! server.favoriteweb.net will auto-failover between PCs.")