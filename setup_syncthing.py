import requests
import json
import time

API_KEY = "Jucqnadf3pASXSwXY7rJazjCFrKcptGP"
BASE = "http://127.0.0.1:8384"
HEADERS = {"X-API-Key": API_KEY}

# First, get current config
print("Getting current config...")
r = requests.get(f"{BASE}/rest/system/config", headers=HEADERS)
config = r.json()
print(f"Current folders: {len(config.get('folders', []))}")
print(f"Current devices: {len(config.get('devices', []))}")

# Accept usage reporting (dismiss the dialog)
print("Setting usage reporting...")
config["options"]["urAccepted"] = -1
config["options"]["urSeen"] = -1

# Add e:\web folder
print("Adding e:\\web folder...")
folder = {
    "id": "web-folder",
    "label": "Web Folder",
    "path": "e:\\web",
    "type": "sendreceive",
    "rescanIntervalS": 3600,
    "fsWatcherEnabled": True,
    "fsWatcherDelayS": 10,
    "ignorePerms": False,
    "autoNormalize": True,
    "filesystemType": "basic",
    "devices": [
        {"deviceID": config["devices"][0]["deviceID"], "introducedBy": "", "encryptionPassword": ""}
    ],
    "minDiskFree": {"unit": "%", "value": 1},
    "versioning": {"type": "", "params": {}, "cleanupIntervalS": 3600, "fsPath": "", "fsType": "basic"},
    "copiers": 0,
    "pullerMaxPendingKiB": 0,
    "hashers": 0,
    "order": "random",
    "ignoreDelete": False,
    "scanProgressIntervalS": 0,
    "pullerPauseS": 0,
    "pullerDelayS": 1,
    "maxConflicts": 10,
    "disableSparseFiles": False,
    "paused": False,
    "markerName": ".stfolder",
    "copyOwnershipFromParent": False,
    "modTimeWindowS": 0,
    "maxConcurrentWrites": 16,
    "disableFsync": False,
    "blockPullOrder": "standard",
    "copyRangeMethod": "standard",
    "caseSensitiveFS": False,
    "junctionsAsDirs": False,
    "syncOwnership": False,
    "sendOwnership": False,
    "syncXattrs": False,
    "sendXattrs": False,
    "blockIndexing": True,
    "xattrFilter": {"maxSingleEntrySize": 1024, "maxTotalSize": 4096}
}

# Remove .stignore from current defaults config
config["folders"] = [folder]

print("Saving config...")
r = requests.post(f"{BASE}/rest/system/config", json=config, headers=HEADERS)
print(f"Config save status: {r.status_code}")
if r.status_code != 200:
    print(f"Error: {r.text}")
else:
    # Restart syncthing to apply config
    print("Restarting Syncthing to apply config...")
    r = requests.post(f"{BASE}/rest/system/restart", headers=HEADERS)
    print(f"Restart status: {r.status_code}")

print("\nDone! Syncthing configured with e:\\web folder.")
print(f"Your Device ID: {config['devices'][0]['deviceID']}")
print("\nOn your other PC:")
print("1. Install Syncthing (same version)")
print("2. Add this device (HCAXOUC...) via 'Add Remote Device'")
print("3. Add the same 'e:\\web' folder")
print("4. Make sure 'Share with device' is enabled")