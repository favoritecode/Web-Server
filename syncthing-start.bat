@echo off
:: Syncthing Auto-Start for e:\web sync
:: This starts Syncthing silently and automatically

start /B /MIN "" "C:\syncthing-windows-amd64-v2.1.1\syncthing.exe" --no-browser --home="C:\Users\KHAN\.config\syncthing"