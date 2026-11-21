<#
GreenGate per-account policy - the ONE place that decides what a protected account's
registry hive contains. Dot-sourced by install.ps1 (at install time) and by
greengate-supervisor.ps1 (every poll, as a safety net).

Why a safety net: on a fresh Windows Home the parent usually creates the child's
account and runs Setup BEFORE the child has ever logged in. At that moment the
account has no profile (no C:\Users\<kid>\NTUSER.DAT), so there is no hive to write
the proxy policy into. The old installer printed a yellow "log in once, then re-run"
and carried on; Setup still said "installed", and the child's Edge went straight to
the internet (found on the Windows 11 Home VM, 2026-11-02).

Two fixes, belt and braces:
  * Set-GreenGateUserPolicy creates the profile itself (userenv!CreateProfile, the same
    call Windows makes at first logon), so the hive exists and the policy lands now.
  * The supervisor calls Confirm-GreenGateUserPolicies every 30 s: any protected
    account that is logged on (HKU\<sid> present) but lacks the policy gets it, so a
    recreated or late-created profile is covered too. Edge and Chrome pick up a policy
    change in the registry without a restart.
#>

$script:GnPolicyCode = @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class GnUserenv {
  [DllImport("userenv.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
  public static extern int CreateProfile(
    [MarshalAs(UnmanagedType.LPWStr)] string pszUserSid,
    [MarshalAs(UnmanagedType.LPWStr)] string pszUserName,
    [Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszProfilePath,
    uint cchProfilePath);
}
'@

function Resolve-GnSid([string]$name) {
  try { (New-Object Security.Principal.NTAccount($name)).Translate(
          [Security.Principal.SecurityIdentifier]).Value } catch { $null }
}

function Get-GnProfilePath([string]$sid) {
  (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\$sid" `
     -Name ProfileImagePath -ErrorAction SilentlyContinue).ProfileImagePath
}

function New-GnProfile([string]$sid, [string]$user) {
  # Returns the profile folder, or $null. Same thing Windows does at first logon, so
  # the account's first real logon finds a normal profile and nothing to redo.
  try {
    if (-not ("GnUserenv" -as [type])) { Add-Type -TypeDefinition $script:GnPolicyCode -Language CSharp -ErrorAction Stop }
    # MAX_PATH exactly: the profile service rejects a bigger buffer with 0x800706F7 (bad stub data)
    $sb = New-Object System.Text.StringBuilder 260
    $hr = [GnUserenv]::CreateProfile($sid, $user, $sb, 260)
    if ($hr -eq 0) { return $sb.ToString() }
    # 0x800700B7 = ERROR_ALREADY_EXISTS: the profile is registered, just use that path
    if (($hr -band 0xFFFF) -eq 0xB7) { return (Get-GnProfilePath $sid) }
    Write-Host ("  CreateProfile for '{0}' failed: 0x{1:X8}" -f $user, $hr) -ForegroundColor Yellow
  } catch { Write-Host "  CreateProfile unavailable: $($_.Exception.Message)" -ForegroundColor Yellow }
  return $null
}

function Test-GreenGateUserPolicy([string]$User, [string]$Proxy = "127.0.0.1:8080") {
  # $true only when the account is logged on (hive mounted) AND carries the policy.
  $sid = Resolve-GnSid $User
  if (-not $sid) { return $false }
  New-PSDrive -PSProvider Registry -Name HKU -Root HKEY_USERS -ErrorAction SilentlyContinue | Out-Null
  if (-not (Test-Path "HKU:\$sid\Software")) { return $false }
  $e = Get-ItemProperty "HKU:\$sid\Software\Policies\Microsoft\Edge" -ErrorAction SilentlyContinue
  $i = Get-ItemProperty "HKU:\$sid\Software\Microsoft\Windows\CurrentVersion\Internet Settings" -ErrorAction SilentlyContinue
  return ($e.ProxyMode -eq "fixed_servers" -and $e.ProxyServer -eq $Proxy -and $i.ProxyEnable -eq 1 -and $i.ProxyServer -eq $Proxy)
}

function Set-GreenGateUserPolicy([string]$User, [string]$Proxy = "127.0.0.1:8080") {
  # Writes the proxy + lock-down policies into ONE account's hive. Creates the profile
  # when the account has never logged in; loads/unloads the hive when it is not mounted.
  # Returns "applied", "created+applied" or a reason it could not.
  $sid = Resolve-GnSid $User
  if (-not $sid) { return "unknown account" }
  New-PSDrive -PSProvider Registry -Name HKU -Root HKEY_USERS -ErrorAction SilentlyContinue | Out-Null
  $loaded = $false; $created = $false
  if (-not (Test-Path "HKU:\$sid\Software")) {
    $prof = Get-GnProfilePath $sid
    if (-not $prof -or -not (Test-Path "$prof\NTUSER.DAT")) {
      $prof = New-GnProfile $sid $User
      if (-not $prof) { return "no profile and could not create one" }
      $created = $true
    }
    & reg.exe load "HKU\$sid" "$prof\NTUSER.DAT" *> $null
    if ($LASTEXITCODE -ne 0) { return "could not open the profile hive (logging in?)" }
    $loaded = $true
  }
  try {
    foreach ($b in "Microsoft\Edge", "Google\Chrome") {
      $k = "HKU:\$sid\Software\Policies\$b"
      New-Item -Path $k -Force | Out-Null
      Set-ItemProperty -Path $k -Name ProxyMode   -Value "fixed_servers"
      Set-ItemProperty -Path $k -Name ProxyServer -Value $Proxy
      Set-ItemProperty -Path $k -Name DeveloperToolsAvailability -Value 2 -Type DWord
      Set-ItemProperty -Path $k -Name BrowserGuestModeEnabled -Value 0 -Type DWord
      # Bing is not on the allowlist, so an address-bar search would hit a block page.
      Set-ItemProperty -Path $k -Name DefaultSearchProviderEnabled -Value 1 -Type DWord
      Set-ItemProperty -Path $k -Name DefaultSearchProviderName -Value "Google"
      Set-ItemProperty -Path $k -Name DefaultSearchProviderSearchURL -Value "https://www.google.com/search?q={searchTerms}"
      Set-ItemProperty -Path $k -Name DefaultSearchProviderSuggestURL -Value "https://www.google.com/complete/search?output=chrome&q={searchTerms}"
      Set-ItemProperty -Path $k -Name NewTabPageLocation -Value "https://www.google.com/"
      New-Item -Path "$k\ExtensionInstallBlocklist" -Force | Out-Null
      Set-ItemProperty -Path "$k\ExtensionInstallBlocklist" -Name "1" -Value "*"
      Remove-Item -Path "$k\ExtensionInstallForcelist" -Recurse -Force -ErrorAction SilentlyContinue
    }
    Set-ItemProperty -Path "HKU:\$sid\Software\Policies\Microsoft\Edge" -Name InPrivateModeAvailability -Value 1 -Type DWord
    Set-ItemProperty -Path "HKU:\$sid\Software\Policies\Google\Chrome"  -Name IncognitoModeAvailability -Value 1 -Type DWord
    # WinINET proxy for that account, for apps that are not Edge or Chrome
    $uis = "HKU:\$sid\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    # Never New-Item -Force an existing key: it recreates it, and an account that has logged in has
    # subkeys there the administrator may not delete ("Attempted to perform an unauthorized operation").
    if (-not (Test-Path $uis)) { New-Item -Path $uis -Force | Out-Null }
    Set-ItemProperty -Path $uis -Name ProxyEnable   -Value 1 -Type DWord
    Set-ItemProperty -Path $uis -Name ProxyServer   -Value $Proxy
    Set-ItemProperty -Path $uis -Name ProxyOverride -Value "<local>"
  } finally {
    if ($loaded) {
      # reg.exe writes "Access is denied" to stderr when a handle is still open; under
      # ErrorActionPreference=Stop that would abort the caller, so retry quietly through cmd.
      [gc]::Collect(); [gc]::WaitForPendingFinalizers()
      for ($try = 0; $try -lt 5; $try++) {
        cmd.exe /c "reg.exe unload HKU\$sid >nul 2>&1"
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Milliseconds 500; [gc]::Collect()
      }
    }
  }
  if ($created) { "created+applied" } else { "applied" }
}

function Confirm-GreenGateUserPolicies([string[]]$Users, [string]$Proxy = "127.0.0.1:8080") {
  # Safety net for the supervisor: only touches accounts that are logged on right now
  # and are missing the policy. Returns the names it repaired.
  $fixed = @()
  New-PSDrive -PSProvider Registry -Name HKU -Root HKEY_USERS -ErrorAction SilentlyContinue | Out-Null
  foreach ($u in $Users) {
    $sid = Resolve-GnSid $u
    if (-not $sid -or -not (Test-Path "HKU:\$sid\Software")) { continue }   # not logged on: nothing to do yet
    if (Test-GreenGateUserPolicy $u $Proxy) { continue }
    try { if ((Set-GreenGateUserPolicy $u $Proxy) -match "applied") { $fixed += $u } } catch { }
  }
  return $fixed
}
