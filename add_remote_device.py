import requests

API_KEY = "Jucqnadf3pASXSwXY7rJazjCFrKcptGP"
BASE = "http://127.0.0.1:8384"
HEADERS = {"X-API-Key": API_KEY}

# Get current config
r = requests.get(f"{BASE}/rest/system/config", headers=HEADERS)
config = r.json()

print(f"Current devices: {[d.get('name','') for d in config['devices']]}")
print(f"Current folders: {[f.get('label','') for f in config['folders']]}")

# Add the other PC's device (HO4JUE5 from 192.168.0.121)
new_device = {
    "deviceID": "HO4JUE5-KFONFSH-DXNF4XL-3DHHG2P-BCNKFTJ-B3GWINS-6U637Z3-YQFVVQV",
    "name": "Other PC (192.168.0.121)",
    "compression": "metadata",
    "introducer": False,
    "skipIntroductionRemovals": False,
    "introducedBy": "",
    "address": "dynamic",
    "paused": False,
    "autoAcceptFolders": False,
    "maxSendKbps": 0,
    "maxRecvKbps": 0,
    "maxRequestKiB": 0,
    "untrusted": False,
    "remoteGUIPort": 0,
    "numConnections": 0
}

# Check if already exists
existing_ids = [d["deviceID"][:7] for d in config["devices"]]
if "HO4JUE5" not in existing_ids:
    config["devices"].append(new_device)
    print("\nAdding remote device: HO4JUE5")
else:
    print("\nDevice HO4JUE5 already in config")

# Share the web-folder with the other PC
for folder in config["folders"]:
    if folder["id"] == "web-folder":
        other_device_short = "HO4JUE5"
        device_in_folder = any(d["deviceID"].startswith("HO4JUE5") for d in folder.get("devices", []))
        if not device_in_folder:
            folder.setdefault("devices", []).append({
                "deviceID": "HO4JUE5-KFONFSH-DXNF4XL-3DHHG2P-BCNKFTJ-B3GWINS-6U637Z3-YQFVVQV",
                "introducedBy": "",
                "encryptionPassword": ""
            })
            print(f"Shared folder '{folder['label']}' with other PC")
        else:
            print(f"Folder '{folder['label']}' already shared with other PC")

# Save config
r = requests.post(f"{BASE}/rest/system/config", json=config, headers=HEADERS)
print(f"\nConfig save status: {r.status_code}")

if r.status_code == 200:
    print("\n✅ Device added & folder shared!")
    print("Restarting Syncthing...")
    requests.post(f"{BASE}/rest/system/restart", headers=HEADERS)
else:
    print(f"Error: {r.text}")