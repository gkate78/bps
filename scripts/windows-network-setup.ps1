# One-time Windows setup so other shop computers can reach BPS running in WSL
# (started with ./scripts/run_local.sh lan).
#
# Run in PowerShell as Administrator:
#   powershell -ExecutionPolicy Bypass -File scripts\windows-network-setup.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\windows-network-setup.ps1 -Remove   (undo firewall rules)
#   Add -AllowTailscale to also allow devices on your Tailscale network (remote access is optional, not set up by default).
#
# What it does:
#   1. Switches WSL to mirrored networking (%USERPROFILE%\.wslconfig) so the app appears on this PC's address.
#   2. Optionally marks the current network as Private (do this only for your shop network).
#   3. With -AllowTailscale: marks the Tailscale network as Private.
#   4. Opens TCP port 8000 on Private networks only, and only to local-network addresses (plus Tailscale with -AllowTailscale).
param(
    [switch]$Remove,
    [switch]$AllowTailscale,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$RuleName = "BPS-App-$Port"
$WslCreatorId = "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}"
# Private LAN ranges; Tailscale's 100.64.0.0/10 only when asked for.
$AllowedRemote = @("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
if ($AllowTailscale) { $AllowedRemote += "100.64.0.0/10" }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "Please run this script in PowerShell as Administrator."
}

Get-NetFirewallHyperVRule -Name $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallHyperVRule
Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
if ($Remove) {
    Write-Host "Removed firewall rules for port $Port. (.wslconfig and network categories were left as they are.)"
    return
}

# 1. Mirrored networking for WSL.
$wslConfig = Join-Path $env:USERPROFILE ".wslconfig"
$lines = @()
if (Test-Path $wslConfig) { $lines = Get-Content $wslConfig }
if ($lines -match '^\s*networkingMode\s*=\s*mirrored\s*$') {
    Write-Host "WSL already uses mirrored networking."
} else {
    if (Test-Path $wslConfig) { Copy-Item $wslConfig "$wslConfig.bak" -Force }
    $lines = $lines | Where-Object { $_ -notmatch '^\s*networkingMode\s*=' }
    $sectionIndex = [array]::IndexOf(@($lines | ForEach-Object { $_.Trim().ToLower() }), "[wsl2]")
    if ($sectionIndex -ge 0) {
        $lines = @($lines[0..$sectionIndex]) + "networkingMode=mirrored" + @($lines | Select-Object -Skip ($sectionIndex + 1))
    } else {
        $lines = @($lines) + "[wsl2]" + "networkingMode=mirrored"
    }
    Set-Content -Path $wslConfig -Value $lines -Encoding ASCII
    Write-Host "Set WSL to mirrored networking in $wslConfig"
}

# 2. Current network category (only mark your shop network as Private).
foreach ($netProfile in Get-NetConnectionProfile | Where-Object { $_.InterfaceAlias -notlike "*Tailscale*" }) {
    if ($netProfile.NetworkCategory -eq "Private") { continue }
    $answer = Read-Host "Is '$($netProfile.Name)' on $($netProfile.InterfaceAlias) your shop's own network? Mark it Private so shop computers can connect (y/N)"
    if ($answer -match '^(y|yes)$') {
        Set-NetConnectionProfile -InterfaceIndex $netProfile.InterfaceIndex -NetworkCategory Private
        Write-Host "Marked '$($netProfile.Name)' as Private."
    } else {
        Write-Host "Left '$($netProfile.Name)' as $($netProfile.NetworkCategory); shop computers won't reach BPS on it."
    }
}

# 3. Tailscale network (optional).
foreach ($netProfile in Get-NetConnectionProfile | Where-Object { $AllowTailscale -and $_.InterfaceAlias -like "*Tailscale*" }) {
    if ($netProfile.NetworkCategory -ne "Private") {
        Set-NetConnectionProfile -InterfaceIndex $netProfile.InterfaceIndex -NetworkCategory Private
        Write-Host "Marked the Tailscale network as Private."
    }
}

# 4. Firewall: Hyper-V firewall governs inbound traffic to WSL in mirrored mode; the regular rule covers the host.
New-NetFirewallHyperVRule -Name $RuleName -DisplayName "BPS app (WSL) TCP $Port" -Direction Inbound `
    -VMCreatorId $WslCreatorId -Protocol TCP -LocalPorts $Port -RemoteAddresses $AllowedRemote `
    -Action Allow -Profiles Private | Out-Null
New-NetFirewallRule -Name $RuleName -DisplayName "BPS app TCP $Port" -Direction Inbound -Protocol TCP `
    -LocalPort $Port -RemoteAddress $AllowedRemote -Action Allow -Profile Private | Out-Null
Write-Host "Opened TCP port $Port on Private networks for: $($AllowedRemote -join ', ')"

Write-Host ""
Write-Host "Next: close your WSL terminals, run 'wsl --shutdown', reopen WSL, and start BPS with:"
Write-Host "  ./scripts/run_local.sh lan"
