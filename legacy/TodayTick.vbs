' TodayTick 启动器：用 pythonw 启动，不弹黑色控制台窗口
Option Explicit
Dim fso, sh, dir, script, pyw
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

dir = fso.GetParentFolderName(WScript.ScriptFullName)
script = dir & "\TodayTick.pyw"

pyw = "C:\Users\EDY\AppData\Local\Programs\Python\Python312\pythonw.exe"
If Not fso.FileExists(pyw) Then pyw = "pythonw.exe"

sh.CurrentDirectory = dir
sh.Run """" & pyw & """ """ & script & """", 0, False
