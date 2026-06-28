import os
import subprocess

root = os.path.dirname(os.path.abspath(__file__))
script = os.path.join(root, "favoriteweb_autostart.ps1")

subprocess.Popen(
    ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
    cwd=root,
    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
)
