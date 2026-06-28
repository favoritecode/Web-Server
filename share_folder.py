import requests

API_KEY = "Jucqnadf3pASXSwXY7rJazjCFrKcptGP"
BASE = "http://127.0.0.1:8384"
HEADERS = {"X-API-Key": API_KEY}

# Get current config
r = requests.get(f"{BASE}/rest/system/config", headers=HEADERS)
config = r.json()

OTHER_DEVICE_ID = "HO4JUE5-5CMUNRC-JTTMZRZ-OJER22D-6WUQZTE-XZ4H5BY-Z27T44I-G6LOHAT"

# Share the web-folder with the other PC
for folder in config["folders"]:
    if folder["id"] == "web-folder":
        device_ids = [d["deviceID"] for d in folder.get("devices", [])]
        if OTHER_DEVICE_ID not in device_ids:
            folder["devices"].append({
                "deviceID": OTHER_DEVICE_ID,
                "introducedBy": "",
                "encryptionPassword": ""
            })
            print(f"✅ Shared '{folder['label']}' with other PC")
        else:
            print(f"ℹ️  '{folder['label']}' already shared")

# Save config
r = requests.post(f"{BASE}/rest/system/config", json=config, headers=HEADERS)
print(f"Config save: {r.status_code}")

if r.status_code == 200:
    print("✅ Config saved! Restarting...")
    requests.post(f"{BASE}/rest/system/restart", headers=HEADERS)
    print("✅ Done! Auto sync will start shortly.")
else:
    print(f"Error: {r.text}")