' PC Remote - silent launcher (no console window)
' Used by the Startup shortcut. Finds pythonw.exe and runs remote.py in the background.

Option Explicit

Dim fso, sh, here, scriptPath, exe
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

here = fso.GetParentFolderName(WScript.ScriptFullName)
scriptPath = here & "\remote.py"

If Not fso.FileExists(scriptPath) Then
    MsgBox "remote.py not found in:" & vbCrLf & here, 48, "PC Remote"
    WScript.Quit 1
End If

exe = FindPythonW()
If exe = "" Then
    MsgBox "pythonw.exe not found. PC Remote cannot start.", 48, "PC Remote"
    WScript.Quit 1
End If

sh.CurrentDirectory = here
On Error Resume Next
sh.Run """" & exe & """ """ & scriptPath & """ 8765", 0, False
If Err.Number <> 0 Then
    MsgBox "Failed to start PC Remote: " & Err.Description, 48, "PC Remote"
End If

Function FindPythonW()
    Dim roots, i, r, p, f

    roots = Array( _
        sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python", _
        sh.ExpandEnvironmentStrings("%USERPROFILE%") & "\.workbuddy\binaries\python\versions", _
        "C:\Python313", _
        "C:\Python312", _
        "C:\Python311" _
    )

    FindPythonW = ""

    For i = 0 To UBound(roots)
        r = roots(i)
        If fso.FolderExists(r) Then
            p = r & "\pythonw.exe"
            If fso.FileExists(p) Then
                FindPythonW = p
                Exit Function
            End If
            For Each f In fso.GetFolder(r).SubFolders
                p = f.Path & "\pythonw.exe"
                If fso.FileExists(p) Then
                    FindPythonW = p
                    Exit Function
                End If
            Next
        End If
    Next
End Function
