<#
GreenGate installer - run in PowerShell **as Administrator** on the kid's Windows PC.

  powershell -ExecutionPolicy Bypass -File .\install.ps1
  powershell -ExecutionPolicy Bypass -File .\install.ps1 -ExemptUsers dad,mom     # extra never-filtered accounts
  powershell -ExecutionPolicy Bypass -File .\install.ps1 -EnforceUsers kid        # filter ONLY this account

What it does
  1. Installs mitmproxy (mitmdump.exe) + the addon into C:\Program Files\GreenGate (admin-only folder)
  2. Runs it as a SYSTEM scheduled task at boot (+ a 5-minute watchdog). Standard users cannot stop it.
  3. Trusts the proxy's certificate machine-wide (needed to inspect youtube.com for the channel filter)
  4. Logs every page the filtered accounts visit, readable at http://greengate.local/log
     (row = URL, column = day, cell = number of hits; blocked attempts listed separately).
     Pass -LogSheetId <id> to also mirror it into a Google Sheet, one tab per month "MM-yyyy".
  5. Forces Google as the default search provider and new tab page (Bing is not on the allowlist).
  6. Points Edge, Chrome and the Windows system proxy at 127.0.0.1:8080 by policy, locks the proxy UI,
     blocks extensions / DevTools / InPrivate so the proxy cannot be bypassed from inside the browser.
Members of the local Administrators group are never filtered; everyone else is.
#>
param(
  [string[]]$ExemptUsers = @(),
  [string[]]$EnforceUsers = @(),
  [int]$Port = 8080,
  # Default control sheet for this build; the setup window pre-fills the same one and
  # lets it be replaced. Keep in step with DEFAULT_SHEET in setup/greengate_setup.py.
  [string]$SheetId = "1VtlZ1FJlUmRQ3VDx7Gzlve7LZ-oHo79P9iFbNj-9VCs",
  [string]$SitesTab = "websites",
  [string]$ChannelsTab = "youtube",
  [string]$LogSheetId = "",                      # Google Sheet id to log visited URLs into
  [string]$LogCredentials = "",                  # its service-account json (default: .\greengate-sheets.json)
  [string]$Relay = "",                           # GreenGate relay URL for screenshots / history (optional)
  [switch]$Consent,                              # a parent AND the child agreed to scheduled screenshots (drive/README.md)
  [string]$MitmVersion = "12.2.3"
)
$ErrorActionPreference = "Stop"
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw "Run this script as Administrator."
}
$Dir  = "C:\Program Files\GreenGate"
# Runtime files go to ProgramData, never Program Files. Controlled Folder Access blocks
# unrecognised binaries from writing into Program Files without saying so, which makes a
# working proxy look like one that never started.
$Data = "C:\ProgramData\GreenGate"
New-Item -ItemType Directory -Force -Path $Data | Out-Null
# admins and SYSTEM may write; the filtered accounts may read their own log, nothing more
& icacls $Data /inheritance:r /grant "*S-1-5-18:(OI)(CI)F" /grant "*S-1-5-32-544:(OI)(CI)F" `
         /grant "*S-1-5-32-545:(OI)(CI)RX" *> $null
Stop-Process -Name mitmdump -Force -ErrorAction SilentlyContinue
$Proxy = "127.0.0.1:$Port"
New-Item -ItemType Directory -Force -Path $Dir, "$Data\ca" | Out-Null

# 1. mitmproxy binary
$bundled = Join-Path $PSScriptRoot "mitmdump.exe"
if ((-not (Test-Path "$Dir\mitmdump.exe")) -and (Test-Path $bundled)) {
  Copy-Item $bundled $Dir -Force                      # shipped inside GreenGate Setup.exe
  Write-Host "Using the bundled mitmproxy"
}
if (-not (Test-Path "$Dir\mitmdump.exe")) {
  Write-Host "Downloading mitmproxy $MitmVersion ..."
  $zip = Join-Path $env:TEMP "mitmproxy-$MitmVersion.zip"
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -Uri "https://downloads.mitmproxy.org/$MitmVersion/mitmproxy-$MitmVersion-windows-x86_64.zip" -OutFile $zip -UseBasicParsing
  $ex = Join-Path $env:TEMP "mitmproxy-$MitmVersion"
  Expand-Archive -Path $zip -DestinationPath $ex -Force
  Copy-Item (Join-Path $ex "mitmdump.exe") $Dir -Force
  Remove-Item $zip, $ex -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not (Test-Path "$Dir\mitmdump.exe")) {
  Write-Host ""
  Write-Host "*** mitmdump.exe is not there after installing it. ***" -ForegroundColor Red
  $det = @(Get-MpThreatDetection -ErrorAction SilentlyContinue |
           Where-Object { "$($_.Resources)" -match "mitmdump|GreenGate" } |
           Sort-Object InitialDetectionTime -Descending | Select-Object -First 5)
  if ($det) {
    Write-Host "Windows Defender removed it:" -ForegroundColor Red
    $det | ForEach-Object { Write-Host "   $($_.InitialDetectionTime)  $($_.Resources)" }
    Write-Host ""
    Write-Host "To allow it, in Windows Security:"
    Write-Host "  1. Virus & threat protection > Protection history"
    Write-Host "  2. find the mitmdump detection, Actions > Restore"
    Write-Host "  3. Manage settings > Exclusions > add $Dir"
    Write-Host "  4. run this installer again"
    Write-Host ""
    Write-Host "GreenGate will not touch your antivirus settings itself."
  } else {
    Write-Host "No Defender detection is recorded - check antivirus or disk permissions on $Dir."
  }
  throw "mitmdump.exe missing - stopping before anything is pointed at a proxy that cannot run."
}
Write-Host "mitmproxy ready: $((Get-Item "$Dir\mitmdump.exe").Length) bytes"

# 2. addon + config (stop a running instance first so the new code is picked up)
Stop-ScheduledTask -TaskName "GreenGate" -ErrorAction SilentlyContinue
Stop-Process -Name mitmdump -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
Copy-Item (Join-Path $PSScriptRoot "greengate.py") $Dir -Force
Copy-Item (Join-Path $PSScriptRoot "sheetlog.py") $Dir -Force
foreach ($py in "policy.py", "timewindow.py") {
  $src = Join-Path $PSScriptRoot $py
  if (Test-Path $src) { Copy-Item $src $Dir -Force } else { throw "$py is missing from the payload - the addon cannot run without it" }
}
$agentExe = Join-Path $PSScriptRoot "GreenGate-Agent.exe"
if (Test-Path $agentExe) { Copy-Item $agentExe $Dir -Force; Copy-Item (Join-Path $PSScriptRoot "timewindow.py") "$Dir\timewindow.py" -Force }
$reset = Join-Path $PSScriptRoot "reset-clean.ps1"
if (Test-Path $reset) { Copy-Item $reset $Dir -Force }        # doubles as the uninstaller
$unlock = Join-Path $PSScriptRoot "GreenGate-Unlock.bat"        # for when the proxy dies
if (Test-Path $unlock) { Copy-Item $unlock $Dir -Force }
foreach ($extra in "greengate-pause.ps1", "diagnose.ps1", "greengate-watchdog.ps1", "greengate-test.ps1", "greengate-supervisor.ps1", "greengate-policy.ps1") {
  $src = Join-Path $PSScriptRoot $extra
  if (Test-Path $src) { Copy-Item $src $Dir -Force }
}
# A one-click way back, on the desktop of whoever installed this - an administrator.
# Not the Public desktop: the kid has no use for it and no need to see it.
if (Test-Path "$Dir\GreenGate-Unlock.bat") {
  try {
    $lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "GreenGate - Khoi phuc mang.lnk"
    $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $sc.TargetPath = "$Dir\GreenGate-Unlock.bat"
    $sc.WorkingDirectory = $Dir
    $sc.Description = "Tra lai ket noi mang neu GreenGate gap su co"
    $sc.Save()
  } catch { Write-Host "(could not create the desktop shortcut: $($_.Exception.Message))" }
}
# "greengate update" from any terminal, for standard users too
$cmd = Get-Content (Join-Path $PSScriptRoot "greengate.cmd") -Raw
$cmd -replace 'set PORT=8080', "set PORT=$Port" |
  Set-Content -Path "$env:SystemRoot\System32\greengate.cmd" -Encoding ASCII
$cfg = @{ exemptUsers = @($ExemptUsers); enforceUsers = @($EnforceUsers)
          dataDir = $Data; logFile = "$Data\greengate.log" }
if ($SheetId) {
  if ($SheetId -match "/spreadsheets/d/([A-Za-z0-9_-]{20,})") { $SheetId = $Matches[1] }
  elseif ($SheetId -match "^([A-Za-z0-9_-]{20,})") { $SheetId = $Matches[1] }   # trailing /edit?usp=...
  $cfg.sheetId = $SheetId; $cfg.sitesTab = $SitesTab; $cfg.channelsTab = $ChannelsTab
  Write-Host "Control sheet: $SheetId (tabs: $SitesTab / $ChannelsTab)"
} else { throw "No control sheet given. Pass -SheetId <link or id>." }
# URL logging is local by default - read it at http://greengate.local/log, no account needed.
$cfg.urlLog = @{ enabled = $true; flushSeconds = 300; sheetAllRequests = $false;
                 localFile = "$Data\urls.jsonl"; localMaxMB = 20 }
if ($LogSheetId) {
  # Optional mirror into Google Sheets, for reading the log away from this PC.
  if (-not $LogCredentials) { $LogCredentials = Join-Path $PSScriptRoot "greengate-sheets.json" }
  if (-not (Test-Path $LogCredentials)) { throw "The sheet mirror needs a service-account key: $LogCredentials not found." }
  Copy-Item $LogCredentials "$Dir\greengate-sheets.json" -Force
  $cfg.urlLog.sheetId = $LogSheetId
  $cfg.urlLog.credentials = "greengate-sheets.json"
  Write-Host "URL log -> local + sheet $LogSheetId"
} else {
  Write-Host "URL log -> local only (http://greengate.local/log)"
}
# NOT Set-Content -Encoding UTF8: on Windows PowerShell 5.1 that writes a BOM.
[System.IO.File]::WriteAllText("$Dir\greengate.json", ($cfg | ConvertTo-Json -Depth 5),
                               (New-Object System.Text.UTF8Encoding($false)))

# 3. scheduled tasks (SYSTEM, at boot, no time limit, restart on failure) + watchdog
$exe = "$Dir\mitmdump.exe"
$arg = "--listen-host 127.0.0.1 --listen-port $Port --set confdir=`"$Data\ca`" -s `"$Dir\greengate.py`" -q"
if (-not (Test-Path "$Dir\greengate-supervisor.ps1")) {
  throw "greengate-supervisor.ps1 was not installed to $Dir - refusing to register a task that points at nothing."
}
# The task runs the SUPERVISOR, which owns mitmdump as its child. Nothing else may
# start the proxy - that is what produced two instances racing for the port.
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Dir\greengate-supervisor.ps1`" -Port $Port"
$trigger = New-ScheduledTaskTrigger -AtStartup
try { $trigger.Delay = "PT15S" } catch {}          # let the network come up first
$trigger2 = New-ScheduledTaskTrigger -AtLogOn      # belt and braces if AtStartup is missed
# No RestartCount/RestartInterval: Task Scheduler restarting the supervisor behind its
# own back is exactly the kind of second owner this design exists to remove. The
# supervisor never exits while it is healthy, and recovers itself when it is not.
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName "GreenGate" -Action $action -Trigger $trigger,$trigger2 -Settings $settings -Principal $principal -Force | Out-Null
# NOT "schtasks /Run /TN GreenGate": Task Scheduler reports a wedged mitmdump as Running,
# so IgnoreNew swallowed that request exactly when recovery was needed. The watchdog now
# proves the proxy serves a request, and force-restarts it - killing every instance - when
# it does not.
$wd = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Dir\greengate-watchdog.ps1`" -Port $Port"
# A -Once trigger whose start time is in the past does NOT resume after a reboot, so the
# watchdog stopped running the moment the PC was restarted. Repeat off a daily trigger and
# fire at startup as well.
$wdt = New-ScheduledTaskTrigger -Daily -At (Get-Date).Date.AddMinutes(1)
$wdt.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) `
  -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
$wdt2 = New-ScheduledTaskTrigger -AtStartup
$wdSet = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -StartWhenAvailable `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "GreenGate Watchdog" -Action $wd -Trigger $wdt,$wdt2 -Settings $wdSet -Principal $principal -Force | Out-Null
# The supervisor may already be running from the AtLogOn trigger that registration
# fires. Asking again is harmless: IgnoreNew keeps it to one, and the supervisor
# itself decides whether the proxy needs starting.
Start-ScheduledTask -TaskName "GreenGate" -ErrorAction SilentlyContinue

# 4. did it ACTUALLY start? The CA file is not proof - an upgrade carries the old one
# over, so it exists whether or not the proxy ever ran. The log and the process are.
$logFile = "$Data\greengate.log"
$up = $false
for ($i = 0; $i -lt 60; $i++) {
  Start-Sleep -Seconds 2
  $c = & curl.exe -s -o NUL -w "%{http_code}" --max-time 5 -x "http://127.0.0.1:$Port" "http://greengate.local/" 2>$null
  if ($c -match "^\d{3}$" -and $c -ne "000") { $up = $true; break }
}
if ($up) {
  Write-Host "Proxy is answering (took $($i * 2)s)."
  # One healthy proxy = two processes (PyInstaller bootstrap + the server it
  # re-executes). Report trees so a working proxy does not look like a duplicate.
  $m = @{}; Get-CimInstance Win32_Process -Filter "Name='mitmdump.exe'" -EA SilentlyContinue |
    ForEach-Object { $m[[int]$_.ProcessId] = [int]$_.ParentProcessId }
  Write-Host "mitmdump proxies: $(@($m.Keys | Where-Object { -not $m.ContainsKey($m[$_]) }).Count)"
} else {
  Write-Host ""
  Write-Host "*** GreenGate did NOT start. Diagnosing... ***" -ForegroundColor Yellow
  $tk = Get-ScheduledTask -TaskName "GreenGate" -EA SilentlyContinue
  if (-not $tk) {
    Write-Host "  the GreenGate task is not registered"
  } else {
    $info = $tk | Get-ScheduledTaskInfo -EA SilentlyContinue
    if ($info) {
      Write-Host ("  task registered, state = {0}, result = 0x{1:X}, last run = {2}" -f `
                  $tk.State, $info.LastTaskResult, $info.LastRunTime)
    } else {
      Write-Host "  task registered (state $($tk.State)) but its run history could not be read"
    }
  }
  Write-Host "  mitmdump.exe present: $(Test-Path "$Dir\mitmdump.exe")"
  Write-Host "  mitmdump process: $(if (Get-Process mitmdump -EA SilentlyContinue) { 'running' } else { 'not running' })"
  Write-Host "  log file        : $(if (Test-Path $logFile) { 'written' } else { 'never written' })"
  Write-Host "  starting it by hand to capture the real error..."
  $o = "$env:TEMP\greengate-start-out.txt"; $e = "$env:TEMP\greengate-start-err.txt"
  try {
    $ph = Start-Process -FilePath "$Dir\mitmdump.exe" -ArgumentList $arg -PassThru `
            -RedirectStandardOutput $o -RedirectStandardError $e -WindowStyle Hidden -EA Stop
    Start-Sleep -Seconds 10
    if (-not $ph.HasExited) {
      $ph.Kill()
      Write-Host "  -> it RUNS when started by hand, so the scheduled task is what is failing." -ForegroundColor Yellow
      Write-Host "     Check Task Scheduler > GreenGate > History, and whether Fast Startup is on."
    } else {
      Write-Host "  -> mitmdump exited immediately with code $($ph.ExitCode):" -ForegroundColor Red
      Get-Content $e, $o -EA SilentlyContinue | Where-Object { $_ } | Select-Object -First 15 |
        ForEach-Object { Write-Host "     $_" }
    }
  } catch {
    Write-Host "  -> could not even launch mitmdump.exe: $($_.Exception.Message)" -ForegroundColor Red
  }
  # NEVER point the machine at a proxy that is not answering. Doing so takes the
  # internet away from every account, including the administrator's - enforceUsers
  # decides who is filtered, not who is routed through the proxy.
  Write-Host "Nothing was pointed at the proxy. Clearing anything an earlier version set," -ForegroundColor Yellow
  Write-Host "this machine keeps working, then stopping." -ForegroundColor Yellow
  Remove-Item "HKLM:\SOFTWARE\Policies\Microsoft\Edge" -Recurse -Force -EA SilentlyContinue
  Remove-Item "HKLM:\SOFTWARE\Policies\Google\Chrome" -Recurse -Force -EA SilentlyContinue
  Remove-ItemProperty "HKLM:\SOFTWARE\Policies\Microsoft\Windows\CurrentVersion\Internet Settings" `
    -Name ProxySettingsPerUser -Force -EA SilentlyContinue
  Remove-ItemProperty "HKLM:\SOFTWARE\Policies\Microsoft\Internet Explorer\Control Panel" `
    -Name Proxy -Force -EA SilentlyContinue
  Set-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings" `
    -Name ProxyEnable -Value 0 -Type DWord -EA SilentlyContinue
  & netsh winhttp reset proxy | Out-Null
  Write-Host ""
  Write-Host "Install stopped. Your internet is untouched. Send the lines above for help." -ForegroundColor Yellow
  exit 1
}

# 5. trust the proxy CA machine-wide
$cer = "$Data\ca\mitmproxy-ca-cert.cer"
for ($i = 0; $i -lt 20 -and -not (Test-Path $cer); $i++) { Start-Sleep -Seconds 1 }
if (Test-Path $cer) {
  certutil -addstore -f Root $cer | Out-Null
} else {
  Write-Host "No CA generated yet - HTTPS will not work until the proxy starts." -ForegroundColor Yellow
}

# 6+7. Route ONLY the chosen accounts through the proxy.
#
# The proxy used to be set machine-wide (ProxySettingsPerUser=0 + HKLM policies). That
# routed every account through it, administrators included - they were never filtered,
# but they were still routed, so a proxy that failed to start took the whole machine
# off the internet. Policies go into each chosen user's own hive instead.
#
# HKCU\Software\Policies is read-only for a standard user, so the kid cannot undo this,
# while an administrator's own profile is left completely untouched.

# The hive writes live in greengate-policy.ps1 so the supervisor can repeat them later.
$policyScript = Join-Path $PSScriptRoot "greengate-policy.ps1"
if (-not (Test-Path $policyScript)) { throw "greengate-policy.ps1 is missing from the payload - cannot protect any account without it" }
. $policyScript
function Resolve-Sid($name) { Resolve-GnSid $name }

$targets = @()
if ($EnforceUsers) {
  $targets = @($EnforceUsers)
} else {
  # S-1-5-32-544, not the word "Administrators": the group name is translated on a
  # localised Windows, and a friend's machine may not be in English.
  $admins = @(Get-LocalGroupMember -SID S-1-5-32-544 -EA SilentlyContinue |
              ForEach-Object { ($_.Name -split '\\')[-1] })
  if (-not $admins) {
    $admins = @(Get-LocalGroupMember -Group Administrators -EA SilentlyContinue |
                ForEach-Object { ($_.Name -split '\\')[-1] })
  }
  $targets = @(Get-LocalUser | Where-Object { $_.Enabled -and $admins -notcontains $_.Name } |
               ForEach-Object { $_.Name })
  $targets = @($targets | Where-Object { $ExemptUsers -notcontains $_ })
}
if (-not $targets) { throw "No accounts to protect. Pass -EnforceUsers <name>." }

foreach ($u in $targets) {
  $sid = Resolve-Sid $u
  if (-not $sid) { Write-Host "Skipping unknown account '$u'" -ForegroundColor Yellow; continue }
  # An account that has never logged in has no hive yet: Set-GreenGateUserPolicy creates
  # the profile first (the old "log in once, then re-run" left the child unfiltered).
  $r = Set-GreenGateUserPolicy $u $Proxy
  if ($r -notmatch "applied") { Write-Host "Could not protect '$u': $r" -ForegroundColor Yellow; continue }
  Write-Host "Protected account: $u$(if ($r -eq 'created+applied') { ' (profile created - the account had never logged in)' })"

  # The agent (screenshots, history, remote refresh, app rules) runs in that account's own
  # session at logon. Its config lives in a per-account file the account may write; the
  # relay URL is pre-filled so pairing is one command: greengate pair
  if (Test-Path "$Dir\GreenGate-Agent.exe") {
    $agentDir = "$Data\agent"
    New-Item -ItemType Directory -Force -Path $agentDir | Out-Null
    $acfg = "$agentDir\$u.json"
    if (-not (Test-Path $acfg)) {
      $a = @{ relay = $Relay; proxyPort = $Port; parents = @(); platform = "windows"; name = "$env:COMPUTERNAME - $u"; consent = @{} }
      [System.IO.File]::WriteAllText($acfg, ($a | ConvertTo-Json -Depth 3), (New-Object System.Text.UTF8Encoding($false)))
    }
    if ($Relay -or $Consent) {
      $a = Get-Content $acfg -Raw | ConvertFrom-Json
      if ($Relay) { $a | Add-Member -NotePropertyName relay -NotePropertyValue $Relay -Force }
      if ($Consent) {
        $now = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
        $a | Add-Member -NotePropertyName consent -NotePropertyValue @{ parent = $now; child = $now } -Force
      }
      [System.IO.File]::WriteAllText($acfg, ($a | ConvertTo-Json -Depth 3), (New-Object System.Text.UTF8Encoding($false)))
    }
    & icacls $agentDir /grant "*${sid}:(OI)(CI)M" *> $null
    $aAct = New-ScheduledTaskAction -Execute "$Dir\GreenGate-Agent.exe" -Argument "--config `"$acfg`" run"
    $aTrg = New-ScheduledTaskTrigger -AtLogOn -User $u
    $aSet = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries `
              -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -Hidden `
              -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
    $aPri = New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName "GreenGate Agent - $u" -Action $aAct -Trigger $aTrg -Settings $aSet -Principal $aPri -Force | Out-Null
    Write-Host "  agent task registered for $u$(if ($Relay) { " (relay $Relay)" } else { " (no relay yet: pair later)" })"
  }
}

# Make sure no machine-wide proxy survives from an earlier version - that is what used
# to knock the administrator off the internet.
Remove-ItemProperty "HKLM:\SOFTWARE\Policies\Microsoft\Windows\CurrentVersion\Internet Settings" -Name ProxySettingsPerUser -Force -EA SilentlyContinue
Remove-ItemProperty "HKLM:\SOFTWARE\Policies\Microsoft\Internet Explorer\Control Panel" -Name Proxy -Force -EA SilentlyContinue
Set-ItemProperty    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings" -Name ProxyEnable -Value 0 -Type DWord -EA SilentlyContinue
foreach ($k in "HKLM:\SOFTWARE\Policies\Microsoft\Edge", "HKLM:\SOFTWARE\Policies\Google\Chrome") {
  Remove-ItemProperty -Path $k -Name ProxyMode, ProxyServer -Force -EA SilentlyContinue
}

# 8. Add/Remove Programs entry - HKLM, so uninstalling needs an administrator
$unKey = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\GreenGate"
if (Test-Path "$Dir\reset-clean.ps1") {
  New-Item -Path $unKey -Force | Out-Null
  Set-ItemProperty -Path $unKey -Name DisplayName     -Value "GreenGate"
  Set-ItemProperty -Path $unKey -Name DisplayVersion  -Value "1.1.0"
  Set-ItemProperty -Path $unKey -Name Publisher       -Value "GreenGate"
  Set-ItemProperty -Path $unKey -Name InstallLocation -Value $Dir
  Set-ItemProperty -Path $unKey -Name NoModify        -Value 1 -Type DWord
  Set-ItemProperty -Path $unKey -Name NoRepair        -Value 1 -Type DWord
  Set-ItemProperty -Path $unKey -Name UninstallString `
    -Value "powershell.exe -ExecutionPolicy Bypass -File `"$Dir\reset-clean.ps1`""
}

Write-Host ""
Write-Host "GreenGate installed. Log: $Data\greengate.log"
Write-Host "If the PC ever loses internet: use the desktop shortcut"
Write-Host "  \"GreenGate - Khoi phuc mang\", or run: greengate unlock"
Write-Host "To check it is behaving: greengate test   (10-minute soak + full report)"
if (Test-Path "$logFile") { Get-Content $logFile -Tail 3 }
Write-Host "Restart the browser (or the PC). Admin accounts are not filtered; standard users are."
