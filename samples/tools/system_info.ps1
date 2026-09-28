# A PowerShell script: runs with powershell -File.
Write-Output "Computer: $env:COMPUTERNAME"
Write-Output "PowerShell $($PSVersionTable.PSVersion)"
Write-Output "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
