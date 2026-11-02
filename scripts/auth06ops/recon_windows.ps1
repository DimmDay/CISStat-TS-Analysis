<#
AUTH-06-OPS-RECON (2026-11-02) - read-only reconnaissance of the Windows
server for the CISStat TS Analysis self-hosted rollout (retire render.com,
own PostgreSQL for the AUTH-05/AUTH-06 first admin bootstrap).

WHAT IT DOES
  Collects hardware, OS, virtualization, docker/wsl, network, DNS, port
  conflict and security facts, then prints a three-level verdict
  (PASS / ATTENTION / FAIL) mapped to the rollout thresholds documented in
  docs/auth06/own-server-recon-plan.md.

WHAT IT DOES NOT DO
  Changes nothing: no service, firewall, registry or file-system mutation.
  Administrator rights are NOT required (a few probes degrade gracefully
  and say so in the report).

HOW TO RUN (regular PowerShell window)
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\auth06ops\recon_windows.ps1 -Domain api.your-domain.ru

  -Domain is optional: it enables the DNS A-record cross-check against the
  detected public IP (that record is required later for the Caddy TLS
  certificate).

OUTPUT (in -OutDir, default ".\cisstat-recon")
  cisstat_recon_<timestamp>.json  full machine-readable report
  cisstat_recon_<timestamp>.txt   human summary to send to the team lead

Compatible with Windows PowerShell 5.1 (no PS7-only syntax, ASCII only).
#>

[CmdletBinding()]
param(
    [string]$Domain = "",
    [string]$OutDir = ".\cisstat-recon"
)

$ErrorActionPreference = "SilentlyContinue"
$ProgressPreference = "SilentlyContinue"

$script:Report = [ordered]@{
    meta           = [ordered]@{}
    host           = [ordered]@{}
    hardware       = [ordered]@{}
    virtualization = [ordered]@{}
    containers     = [ordered]@{}
    network        = [ordered]@{}
    conflicts      = [ordered]@{}
    verdict        = @()
}

$script:Checks = New-Object System.Collections.Generic.List[object]

function Add-Fact {
    param([string]$Section, [string]$Key, $Value)
    $script:Report[$Section][$Key] = $Value
}

function Add-Check {
    param([string]$Name, [string]$Level, [string]$Detail)
    $script:Checks.Add([ordered]@{ name = $Name; level = $Level; detail = $Detail })
}

function ConvertTo-Gb {
    param($Bytes)
    if ($null -eq $Bytes) { return $null }
    return [math]::Round([double]$Bytes / 1GB, 2)
}

function Test-PrivateOrCgnatIp {
    param([string]$Ip)
    $parts = $Ip.Split(".")
    if ($parts.Count -ne 4) { return "invalid" }
    $a = 0
    $b = 0
    if (-not [int]::TryParse($parts[0], [ref]$a)) { return "invalid" }
    if (-not [int]::TryParse($parts[1], [ref]$b)) { return "invalid" }
    if ($a -eq 10) { return "private" }
    if ($a -eq 172 -and $b -ge 16 -and $b -le 31) { return "private" }
    if ($a -eq 192 -and $b -eq 168) { return "private" }
    if ($a -eq 169 -and $b -eq 254) { return "link_local" }
    if ($a -eq 100 -and $b -ge 64 -and $b -le 127) { return "cgnat" }
    if ($a -eq 127) { return "loopback" }
    return "public"
}

function Get-PublicIp {
    $sources = @("https://api.ipify.org", "https://ipinfo.io/ip")
    foreach ($url in $sources) {
        try {
            $ip = Invoke-RestMethod -Uri $url -TimeoutSec 10
            if ($ip) {
                $candidate = ([string]$ip).Trim()
                if ((Test-PrivateOrCgnatIp -Ip $candidate) -eq "public") { return $candidate }
            }
        } catch { }
    }
    return ""
}

# ---------------------------------------------------------------- meta
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$isAdmin = $false
try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
} catch { $isAdmin = $false }

Add-Fact -Section "meta" -Key "task" -Value "AUTH-06-OPS-RECON (read-only recon, repo base 2299ad0)"
Add-Fact -Section "meta" -Key "generated_at" -Value $stamp
Add-Fact -Section "meta" -Key "domain_param" -Value $Domain
Add-Fact -Section "meta" -Key "is_admin" -Value $isAdmin
Add-Fact -Section "meta" -Key "powershell_version" -Value $PSVersionTable.PSVersion.ToString()
Add-Fact -Section "meta" -Key "powershell_edition" -Value $PSVersionTable.PSEdition

# ---------------------------------------------------------------- host
$cs = $null
$os = $null
$cpu = $null
try { $cs = Get-CimInstance -ClassName Win32_ComputerSystem } catch { }
try { $os = Get-CimInstance -ClassName Win32_OperatingSystem } catch { }
try { $cpu = Get-CimInstance -ClassName Win32_Processor | Select-Object -First 1 } catch { }

if ($os) {
    Add-Fact -Section "host" -Key "os_caption" -Value $os.Caption
    Add-Fact -Section "host" -Key "os_version" -Value ($os.Version + " build " + $os.BuildNumber)
    Add-Fact -Section "host" -Key "os_architecture" -Value $os.OSArchitecture
    Add-Fact -Section "host" -Key "installed_at" -Value $os.InstallDate
    $boot = $os.LastBootUpTime
    Add-Fact -Section "host" -Key "last_boot" -Value $boot
    if ($boot) {
        try {
            $uptimeHours = [math]::Round(((Get-Date) - $boot).TotalHours, 1)
            Add-Fact -Section "host" -Key "uptime_hours" -Value $uptimeHours
        } catch { }
    }
}
if ($cs) {
    Add-Fact -Section "host" -Key "computer_name" -Value $cs.Name
    Add-Fact -Section "host" -Key "manufacturer_model" -Value ($cs.Manufacturer + " " + $cs.Model)
    Add-Fact -Section "host" -Key "domain_joined" -Value $cs.Domain
    Add-Fact -Section "host" -Key "pc_system_type_code" -Value $cs.PCSystemType
}
try {
    $tz = (Get-TimeZone).Id
    Add-Fact -Section "host" -Key "timezone" -Value $tz
} catch { }

$batteryPresent = $false
try { $batteryPresent = [bool](Get-CimInstance -ClassName Win32_Battery) } catch { }
Add-Fact -Section "host" -Key "battery_present" -Value $batteryPresent

# ------------------------------------------------------------- hardware
if ($cpu) {
    Add-Fact -Section "hardware" -Key "cpu_name" -Value $cpu.Name
    Add-Fact -Section "hardware" -Key "cpu_cores" -Value $cpu.NumberOfCores
    Add-Fact -Section "hardware" -Key "cpu_logical" -Value $cpu.NumberOfLogicalProcessors
    Add-Fact -Section "hardware" -Key "cpu_max_clock_mhz" -Value $cpu.MaxClockSpeed
}
if ($cs) {
    Add-Fact -Section "hardware" -Key "ram_total_gb" -Value (ConvertTo-Gb -Bytes $cs.TotalPhysicalMemory)
}
if ($os) {
    Add-Fact -Section "hardware" -Key "ram_free_gb" -Value (ConvertTo-Gb -Bytes ($os.FreePhysicalMemory * 1KB))
}

$logicalDisks = @()
try {
    $logicalDisks = Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DriveType=3"
} catch { }
$diskList = New-Object System.Collections.Generic.List[object]
foreach ($disk in $logicalDisks) {
    $freePct = $null
    if ($disk.Size -and $disk.Size -gt 0) {
        $freePct = [math]::Round(100.0 * $disk.FreeSpace / $disk.Size, 1)
    }
    $diskList.Add([ordered]@{
        drive       = $disk.DeviceID
        size_gb     = (ConvertTo-Gb -Bytes $disk.Size)
        free_gb     = (ConvertTo-Gb -Bytes $disk.FreeSpace)
        free_percent = $freePct
    })
}
Add-Fact -Section "hardware" -Key "logical_disks" -Value $diskList

$physicalMedia = New-Object System.Collections.Generic.List[object]
if (Get-Command Get-PhysicalDisk -ErrorAction SilentlyContinue) {
    try {
        foreach ($pd in (Get-PhysicalDisk)) {
            $physicalMedia.Add([ordered]@{
                disk    = $pd.FriendlyName
                media   = $pd.MediaType
                bus     = $pd.BusType
                size_gb = (ConvertTo-Gb -Bytes $pd.Size)
            })
        }
    } catch { }
}
Add-Fact -Section "hardware" -Key "physical_media" -Value $physicalMedia

# ------------------------------------------------------- virtualization
$hypervisorPresent = $false
$virtFirmware = $false
if ($cs) { $hypervisorPresent = [bool]$cs.HypervisorPresent }
if ($cpu) { $virtFirmware = [bool]$cpu.VirtualizationFirmwareEnabled }
Add-Fact -Section "virtualization" -Key "hypervisor_present" -Value $hypervisorPresent
Add-Fact -Section "virtualization" -Key "virtualization_firmware_enabled" -Value $virtFirmware

$featureStates = New-Object System.Collections.Generic.List[object]
if ($isAdmin) {
    foreach ($feature in @("Microsoft-Windows-Subsystem-Linux", "VirtualMachinePlatform", "Microsoft-Hyper-V-All")) {
        $state = "unknown"
        try { $state = [string](Get-WindowsOptionalFeature -Online -FeatureName $feature).State } catch { $state = "probe_failed" }
        $featureStates.Add([ordered]@{ feature = $feature; state = $state })
    }
} else {
    $featureStates.Add([ordered]@{ feature = "wsl_vmp_hyperv"; state = "requires_admin_run" })
}
Add-Fact -Section "virtualization" -Key "windows_optional_features" -Value $featureStates

try {
    $plan = Get-CimInstance -Namespace "root/cimv2/power" -ClassName Win32_PowerPlan | Where-Object { $_.IsActive }
    if ($plan) { Add-Fact -Section "virtualization" -Key "active_power_plan" -Value $plan.ElementName }
} catch { }

# ------------------------------------------------------------ containers
$dockerPresent = $false
try { $dockerPresent = [bool](Get-Command docker -ErrorAction SilentlyContinue) } catch { }
$dockerVersion = ""
$composeVersion = ""
$dockerDaemonRunning = $false
if ($dockerPresent) {
    try { $dockerVersion = ((& docker --version) 2>$null | Out-String).Trim() } catch { $dockerVersion = "probe_failed" }
    try { $composeVersion = ((& docker compose version) 2>$null | Out-String).Trim() } catch { $composeVersion = "probe_failed" }
    try {
        $null = (& docker ps) 2>$null
        $dockerDaemonRunning = ($LASTEXITCODE -eq 0)
    } catch { $dockerDaemonRunning = $false }
}
Add-Fact -Section "containers" -Key "docker_present" -Value $dockerPresent
Add-Fact -Section "containers" -Key "docker_version" -Value $dockerVersion
Add-Fact -Section "containers" -Key "docker_compose_version" -Value $composeVersion
Add-Fact -Section "containers" -Key "docker_daemon_running" -Value $dockerDaemonRunning

$env:WSL_UTF8 = "1"
$wslPresent = $false
try { $wslPresent = [bool](Get-Command wsl.exe -ErrorAction SilentlyContinue) } catch { }
$wslStatus = ""
$wslList = ""
if ($wslPresent) {
    try { $wslStatus = ((& wsl.exe --status) 2>&1 | Out-String).Trim() -replace "\x00", "" } catch { $wslStatus = "probe_failed" }
    try { $wslList = ((& wsl.exe -l -v) 2>&1 | Out-String).Trim() -replace "\x00", "" } catch { $wslList = "probe_failed" }
}
Add-Fact -Section "containers" -Key "wsl_present" -Value $wslPresent
Add-Fact -Section "containers" -Key "wsl_status" -Value $wslStatus
Add-Fact -Section "containers" -Key "wsl_distros" -Value $wslList

# --------------------------------------------------------------- network
$publicIp = Get-PublicIp
Add-Fact -Section "network" -Key "public_ip" -Value $publicIp

$localIps = @()
try {
    $localIps = Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -ne "127.0.0.1" } |
        Select-Object -ExpandProperty IPAddress
} catch { }
Add-Fact -Section "network" -Key "local_ipv4" -Value $localIps

try {
    $gateway = (Get-NetRoute -DestinationPrefix "0.0.0.0/0" | Sort-Object RouteMetric | Select-Object -First 1).NextHop
    Add-Fact -Section "network" -Key "default_gateway" -Value $gateway
} catch { }

try {
    $dnsServers = (Get-DnsClientServerAddress -AddressFamily IPv4 | Select-Object -First 1).ServerAddresses
    Add-Fact -Section "network" -Key "dns_servers" -Value $dnsServers
} catch { }

$publicClass = "unknown"
if ($publicIp) { $publicClass = Test-PrivateOrCgnatIp -Ip $publicIp }
Add-Fact -Section "network" -Key "public_ip_class" -Value $publicClass

$directPublic = $false
if ($publicIp -and $localIps) { $directPublic = [bool]($localIps -contains $publicIp) }
Add-Fact -Section "network" -Key "public_ip_on_local_adapter" -Value $directPublic

$firewall = New-Object System.Collections.Generic.List[object]
try {
    foreach ($profile in (Get-NetFirewallProfile)) {
        $firewall.Add([ordered]@{ profile = $profile.Name; enabled = $profile.Enabled })
    }
} catch { }
Add-Fact -Section "network" -Key "firewall_profiles" -Value $firewall

$domainRecordIp = ""
$domainStatus = "not_requested"
if ($Domain) {
    try {
        $answers = Resolve-DnsName -Name $Domain -Type A -ErrorAction SilentlyContinue
        $first = $answers | Where-Object { $_.IPAddress } | Select-Object -First 1
        if ($first) {
            $domainRecordIp = [string]$first.IPAddress
            if ($domainRecordIp -eq $publicIp) { $domainStatus = "matches_public_ip" }
            else { $domainStatus = "mismatch_or_not_propagated" }
        } else {
            $domainStatus = "no_a_record"
        }
    } catch {
        $domainStatus = "resolver_unavailable"
    }
}
Add-Fact -Section "network" -Key "domain_record_ip" -Value $domainRecordIp
Add-Fact -Section "network" -Key "domain_status" -Value $domainStatus

# ------------------------------------------------------------- conflicts
$listeners = New-Object System.Collections.Generic.List[object]
try {
    $ports = Get-NetTCPConnection -State Listen |
        Where-Object { $_.LocalPort -in @(22, 80, 443, 8000, 5432) } |
        Sort-Object LocalPort -Unique
    foreach ($listener in $ports) {
        $procName = ""
        try { $procName = (Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue).ProcessName } catch { }
        $listeners.Add([ordered]@{ port = $listener.LocalPort; process = $procName })
    }
} catch { }
Add-Fact -Section "conflicts" -Key "listening_ports" -Value $listeners

$iisStatus = "probe_failed"
try {
    $iis = Get-Service -Name W3SVC -ErrorAction SilentlyContinue
    if ($iis) { $iisStatus = [string]$iis.Status } else { $iisStatus = "absent" }
} catch { }
Add-Fact -Section "conflicts" -Key "iis_w3svc" -Value $iisStatus

$sshdStatus = "probe_failed"
try {
    $sshd = Get-Service -Name sshd -ErrorAction SilentlyContinue
    if ($sshd) { $sshdStatus = [string]$sshd.Status } else { $sshdStatus = "absent" }
} catch { }
Add-Fact -Section "conflicts" -Key "openssh_server" -Value $sshdStatus

$pgServices = New-Object System.Collections.Generic.List[object]
try {
    foreach ($svc in (Get-Service | Where-Object { $_.Name -like "postgres*" })) {
        $pgServices.Add([ordered]@{ service = $svc.Name; status = [string]$svc.Status })
    }
} catch { }
Add-Fact -Section "conflicts" -Key "native_postgres_services" -Value $pgServices

# ------------------------------------------------------------- processes
$topRam = New-Object System.Collections.Generic.List[object]
try {
    foreach ($p in (Get-Process | Sort-Object -Property WS -Descending | Select-Object -First 5)) {
        $topRam.Add([ordered]@{ process = $p.ProcessName; working_set_gb = [math]::Round($p.WS / 1GB, 2) })
    }
} catch { }
Add-Fact -Section "conflicts" -Key "top5_processes_by_ram" -Value $topRam

# --------------------------------------------------------------- verdict
$totalRamGb = $null
if ($cs) { $totalRamGb = ConvertTo-Gb -Bytes $cs.TotalPhysicalMemory }
$cores = $null
if ($cpu) {
    $cores = $cpu.NumberOfCores
    if (-not $cores) { $cores = $cpu.NumberOfLogicalProcessors }
}
$systemFreeGb = $null
foreach ($entry in $diskList) {
    if ($entry.drive -and $env:SystemDrive -and $entry.drive.StartsWith($env:SystemDrive)) {
        $systemFreeGb = $entry.free_gb
    }
}

if ($cores -and $cores -ge 2) {
    Add-Check -Name "cpu_cores" -Level "PASS" -Detail ("cores: " + $cores + " (threshold 2)")
} else {
    Add-Check -Name "cpu_cores" -Level "FAIL" -Detail ("cores: " + $cores + " - below the 2-core threshold for the api image")
}

if ($null -ne $totalRamGb) {
    if ($totalRamGb -ge 4) {
        Add-Check -Name "ram_total_gb" -Level "PASS" -Detail ("total: " + $totalRamGb + " GB (threshold 4; 8+ comfortable)")
    } elseif ($totalRamGb -ge 3) {
        Add-Check -Name "ram_total_gb" -Level "ATTENTION" -Detail ("total: " + $totalRamGb + " GB - tight for uvicorn with torch plus postgres")
    } else {
        Add-Check -Name "ram_total_gb" -Level "FAIL" -Detail ("total: " + $totalRamGb + " GB - below the 3 GB hard floor")
    }
} else {
    Add-Check -Name "ram_total_gb" -Level "FAIL" -Detail "cannot read total RAM"
}

if ($null -ne $systemFreeGb) {
    if ($systemFreeGb -ge 35) {
        Add-Check -Name "system_drive_free_gb" -Level "PASS" -Detail ("free: " + $systemFreeGb + " GB (api image plus postgres plus OS need 30-40)")
    } elseif ($systemFreeGb -ge 20) {
        Add-Check -Name "system_drive_free_gb" -Level "ATTENTION" -Detail ("free: " + $systemFreeGb + " GB - will fill up with images and logs over time")
    } else {
        Add-Check -Name "system_drive_free_gb" -Level "FAIL" -Detail ("free: " + $systemFreeGb + " GB - insufficient for the api image")
    }
} else {
    Add-Check -Name "system_drive_free_gb" -Level "FAIL" -Detail "cannot read system drive free space"
}

$arch = ""
if ($os) { $arch = [string]$os.OSArchitecture }
if ($arch -match "64") {
    Add-Check -Name "os_architecture" -Level "PASS" -Detail ("architecture: " + $arch)
} else {
    Add-Check -Name "os_architecture" -Level "FAIL" -Detail ("architecture: " + $arch + " - 64-bit is required")
}

if ($hypervisorPresent -or $virtFirmware) {
    Add-Check -Name "virtualization_for_docker" -Level "PASS" -Detail ("hypervisor_present: " + $hypervisorPresent + "; firmware_flag: " + $virtFirmware)
} else {
    Add-Check -Name "virtualization_for_docker" -Level "FAIL" -Detail "neither hypervisor present nor firmware virtualization flag - enable VT-x/AMD-V in UEFI for the Windows docker path"
}

if ($os -and $os.Caption -match "Server") {
    Add-Check -Name "windows_edition" -Level "PASS" -Detail ($os.Caption + " - server edition; the plan still recommends Linux for production")
} else {
    Add-Check -Name "windows_edition" -Level "ATTENTION" -Detail "desktop edition: Windows Update auto-reboots break API uptime; the plan recommends wiping this machine to Ubuntu Server 24.04 LTS for production"
}

$uptimeHours = $null
try { $uptimeHours = $script:Report["host"]["uptime_hours"] } catch { }
if ($null -ne $uptimeHours -and $uptimeHours -lt 48) {
    Add-Check -Name "uptime_hours" -Level "ATTENTION" -Detail ("last boot " + $uptimeHours + " h ago - confirm the machine is always-on (24/7)")
} else {
    Add-Check -Name "uptime_hours" -Level "PASS" -Detail "uptime window looks stable for an always-on host"
}

if (-not $publicIp) {
    Add-Check -Name "public_ip" -Level "FAIL" -Detail "cannot determine public IP - check internet connectivity"
} else {
    Add-Check -Name "public_ip" -Level "PASS" -Detail ("public IP: " + $publicIp + " (class: " + $publicClass + ")")
}

if ($publicClass -eq "cgnat") {
    Add-Check -Name "nat_classification" -Level "FAIL" -Detail "CGNAT (100.64.0.0/10): inbound 80/443 impossible without an ISP change or relay - blocker for self-hosting"
} elseif ($publicClass -eq "private") {
    Add-Check -Name "nat_classification" -Level "ATTENTION" -Detail "public lookup returned a private-range address - verify the gateway WAN IP and router port forwarding for 80/443"
} elseif ($directPublic) {
    Add-Check -Name "nat_classification" -Level "PASS" -Detail "public IP sits on a local adapter - direct exposure, still keep firewall 22/80/443 only"
} elseif ($publicClass -eq "public") {
    Add-Check -Name "nat_classification" -Level "ATTENTION" -Detail "behind NAT: configure router port forwarding for 80/443 to this host (or get a white IP from the ISP)"
}

if (-not $Domain) {
    Add-Check -Name "domain_dns" -Level "ATTENTION" -Detail "run again with -Domain api.your-domain.ru to verify the A-record against the public IP (required for the Caddy TLS certificate)"
} elseif ($domainStatus -eq "matches_public_ip") {
    Add-Check -Name "domain_dns" -Level "PASS" -Detail ($Domain + " resolves to the detected public IP")
} elseif ($domainStatus -eq "mismatch_or_not_propagated") {
    Add-Check -Name "domain_dns" -Level "ATTENTION" -Detail ($Domain + " resolves to " + $domainRecordIp + " while the public IP is " + $publicIp + " - update the A-record or wait for propagation")
} elseif ($domainStatus -eq "no_a_record") {
    Add-Check -Name "domain_dns" -Level "FAIL" -Detail ($Domain + " has no A-record yet - create it before the TLS phase")
} else {
    Add-Check -Name "domain_dns" -Level "FAIL" -Detail ("DNS check failed: " + $domainStatus)
}

$busyPorts = @()
foreach ($item in $listeners) {
    if (($item.port -eq 80 -or $item.port -eq 443) -and $item.process -and $item.process -ne "System" -and $item.process -ne "Idle") {
        $busyPorts = $busyPorts + ([string]$item.port + " by " + $item.process)
    }
}
if ($busyPorts.Count -eq 0) {
    Add-Check -Name "ports_80_443" -Level "PASS" -Detail "no third-party listeners on 80/443 (caddy will bind them)"
} else {
    Add-Check -Name "ports_80_443" -Level "ATTENTION" -Detail ("occupied: " + ($busyPorts -join ", ") + " - free them before the caddy phase")
}

if ($dockerDaemonRunning) {
    Add-Check -Name "docker_runtime" -Level "PASS" -Detail ("docker present and running: " + $dockerVersion)
} elseif ($dockerPresent) {
    Add-Check -Name "docker_runtime" -Level "ATTENTION" -Detail "docker installed but the daemon is not running"
} else {
    Add-Check -Name "docker_runtime" -Level "ATTENTION" -Detail "docker absent - expected if this machine will be wiped to Linux (docker engine is installed there); required if staying on Windows"
}

$hasHdd = $false
$mediaKnown = $false
foreach ($entry in $physicalMedia) {
    if ($entry.media) { $mediaKnown = $true }
    if ($entry.media -eq "HDD") { $hasHdd = $true }
}
if ($hasHdd) {
    Add-Check -Name "disk_media" -Level "ATTENTION" -Detail "HDD detected - model fitting and backtests will be slow; prefer SSD"
} elseif ($mediaKnown) {
    Add-Check -Name "disk_media" -Level "PASS" -Detail "no HDD in the physical media list"
} else {
    Add-Check -Name "disk_media" -Level "ATTENTION" -Detail "media type undetermined (an admin run enables the storage probe) - verify SSD manually"
}

if ($batteryPresent) {
    Add-Check -Name "chassis_power" -Level "ATTENTION" -Detail "battery present - laptop-class host: disable sleep/hibernate on AC and ensure 24/7 power"
} else {
    Add-Check -Name "chassis_power" -Level "PASS" -Detail "no battery - desktop/server class chassis"
}

if ($sshdStatus -eq "Running") {
    Add-Check -Name "openssh_server" -Level "PASS" -Detail "OpenSSH server running - the operator tunnel for migrate/bootstrap is ready"
} else {
    Add-Check -Name "openssh_server" -Level "ATTENTION" -Detail ("OpenSSH server state: " + $sshdStatus + " - needed for operator commands over an SSH tunnel after the move")
}

$script:Report["verdict"] = $script:Checks

$fails = @($script:Checks | Where-Object { $_.level -eq "FAIL" })
$attentions = @($script:Checks | Where-Object { $_.level -eq "ATTENTION" })

# ---------------------------------------------------------------- output
if (-not (Test-Path -LiteralPath $OutDir)) {
    [void][System.IO.Directory]::CreateDirectory($OutDir)
}
$fileStamp = Get-Date -Format "yyyyMMdd_HHmmss"
$jsonPath = Join-Path $OutDir ("cisstat_recon_" + $fileStamp + ".json")
$txtPath = Join-Path $OutDir ("cisstat_recon_" + $fileStamp + ".txt")

$json = $script:Report | ConvertTo-Json -Depth 8
$noBomEncoding = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($jsonPath, $json, $noBomEncoding)

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("CISStat TS Analysis - AUTH-06-OPS-RECON (read-only recon)")
$lines.Add("generated: " + $stamp + " | admin: " + $isAdmin + " | domain param: " + $Domain)
$lines.Add("")
$lines.Add("VERDICT (" + $fails.Count + " FAIL / " + $attentions.Count + " ATTENTION / " + ($script:Checks.Count - $fails.Count - $attentions.Count) + " PASS)")
foreach ($check in $script:Checks) {
    $lines.Add(("[" + $check.level.PadRight(9) + "] " + $check.name + " :: " + $check.detail))
}
$lines.Add("")
if ($fails.Count -eq 0) {
    $lines.Add("RESULT: NO BLOCKERS - proceed with docs/auth06/own-server-recon-plan.md phases (ATTENTION items are decisions, not stoppers)")
} else {
    $lines.Add("RESULT: " + $fails.Count + " BLOCKER(S) - resolve the FAIL lines before the move (plan section 6)")
}
$lines.Add("")
$lines.Add("report: " + $jsonPath)
[System.IO.File]::WriteAllText($txtPath, ($lines -join [Environment]::NewLine), $noBomEncoding)

foreach ($line in $lines) { Write-Host $line }
Write-Host ""
Write-Host ("Send BOTH files to the team lead: " + $jsonPath + " and " + $txtPath)
exit 0
