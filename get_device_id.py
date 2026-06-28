import requests

API_KEY = "Jucqnadf3pASXSwXY7rJazjCFrKcptGP"
BASE = "http://127.0.0.1:8384"
HEADERS = {"X-API-Key": API_KEY}

# Get connections to see other device IDs
r = requests.get(f"{BASE}/rest/system/connections", headers=HEADERS)
connections = r.json()
print("Connected devices:")
for dev_id, info in connections.get("connections", {}).items():
    print(f"  Full Device ID: {dev_id}")
    print(f"  Name: {info.get('name', 'N/A')}")
    print(f"  Address: {info.get('address', 'N/A')}")
    print(f"  Client: {info.get('clientVersion', 'N/A')}")
    print()

# Also get the config to see what's already there
r2 = requests.get(f"{BASE}/rest/system/config", headers=HEADERS)
config = r2.json()
print("Devices in config:")
for d in config["devices"]:
    print(f"  {d.get('name','')}: {d['deviceID']}")
print()
print("Folders:")
for f in config["folders"]:
    print(f"  {f.get('label','')} (id={f['id']})")
    for d in f.get("devices", []):
        print(f"    - shared with device: {d['deviceID'][:7]}...")