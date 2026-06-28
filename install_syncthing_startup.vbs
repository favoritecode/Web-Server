Set WSO = CreateObject("WScript.Shell")
startupFolder = WSO.SpecialFolders("Startup")

' First try: use syncthing-autostart.bat (auto-detects location)
Set SC = WSO.CreateShortcut(startupFolder & "\Syncthing.lnk")
SC.TargetPath = "e:\web\syncthing-autostart.bat"
SC.WorkingDirectory = "e:\web"
SC.WindowStyle = 7
SC.Save

MsgBox "Syncthing auto-start added to Windows Startup!" & vbCrLf & vbCrLf & "Next time you restart, Syncthing will start automatically.", vbInformation, "Done"