$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Syncthing.lnk")
$sc.TargetPath = "e:\web\syncthing-start.bat"
$sc.WorkingDirectory = "e:\web"
$sc.WindowStyle = 7
$sc.Save()
Write-Host "✅ Syncthing startup shortcut created!"