# Gives Teto her icon everywhere: Desktop + Start menu shortcuts, a "Teto"
# shortcut inside her folder, and a Teto icon on the folder itself.
param([Parameter(Mandatory = $true)][string]$AppDir)
$ErrorActionPreference = 'SilentlyContinue'
$icon = Join-Path $AppDir 'assets\teto.ico'
$pyw = Join-Path $AppDir '.venv\Scripts\pythonw.exe'
$main = Join-Path $AppDir 'main.py'
$shell = New-Object -ComObject WScript.Shell
$places = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'), $AppDir)
foreach ($dir in $places) {
    $lnk = $shell.CreateShortcut((Join-Path $dir 'Teto.lnk'))
    $lnk.TargetPath = $pyw
    $lnk.Arguments = '"' + $main + '"'
    $lnk.WorkingDirectory = $AppDir
    $lnk.IconLocation = "$icon,0"
    $lnk.Description = 'Teto Desktop Agent'
    $lnk.Save()
}
# Folder icon (Explorer reads desktop.ini when the folder has the System attribute)
$ini = Join-Path $AppDir 'desktop.ini'
if (Test-Path $ini) { attrib -s -h $ini }
Set-Content -Path $ini -Encoding Unicode -Value "[.ShellClassInfo]`r`nIconResource=assets\teto.ico,0`r`nInfoTip=Teto Desktop Agent"
attrib +s +h $ini
attrib +s $AppDir
