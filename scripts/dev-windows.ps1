[CmdletBinding()]
param(
    [ValidateSet("Start", "Stop", "Restart", "Status")]
    [string]$Action = "Restart",
    [ValidateRange(10, 180)]
    [int]$StartupTimeoutSeconds = 60,
    [switch]$ForcePortCleanup
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendRoot = Join-Path $RepoRoot "backend"
$RuntimeRoot = Join-Path $RepoRoot ".dev-windows"
$StateFile = Join-Path $RuntimeRoot "state.json"
$ApiPort = 8080
$UiPort = 3000

# Some Windows hosts expose both Path and PATH in the inherited environment.
# Windows PowerShell's Start-Process rejects that duplicate pair. This launcher
# runs in a child shell, so normalizing it here does not modify the caller.
$pathKeys = @([Environment]::GetEnvironmentVariables("Process").Keys | Where-Object { $_ -ieq "Path" })
if ($pathKeys.Count -gt 1) {
    $inheritedPath = $env:Path
    Remove-Item Env:PATH -ErrorAction SilentlyContinue
    $env:Path = $inheritedPath
}

function Write-Step([string]$Message) {
    Write-Host "[rv-dashboard] $Message"
}

function Get-ListenerProcessIds([int]$Port) {
    $netstat = Join-Path $env:SystemRoot "System32\netstat.exe"
    $pattern = "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
    # Do not pass `-p tcp`: Windows treats TCP and TCPv6 separately, while
    # Vinext commonly binds localhost as [::1]. The unfiltered output includes
    # both families and the regex below still accepts only TCP listeners.
    $identifiers = foreach ($line in (& $netstat -ano 2>$null)) {
        if ($line -match $pattern) {
            [int]$Matches[1]
        }
    }
    @($identifiers | Sort-Object -Unique)
}

function Get-ProcessCommandLine([int]$ProcessId) {
    try {
        (Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop).CommandLine
    }
    catch {
        ""
    }
}

function Stop-ProcessTree([int]$ProcessId, [string]$Label) {
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $process) {
        return
    }

    Write-Step "Stopping $Label (PID $ProcessId)"
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    $exitDeadline = (Get-Date).AddSeconds(5)
    while ((Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) -and (Get-Date) -lt $exitDeadline) {
        Start-Sleep -Milliseconds 100
    }
    if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
        $taskkill = Join-Path $env:SystemRoot "System32\taskkill.exe"
        Start-Process -FilePath $taskkill -ArgumentList @("/PID", [string]$ProcessId, "/T", "/F") `
            -WindowStyle Hidden -Wait | Out-Null
        $exitDeadline = (Get-Date).AddSeconds(5)
        while ((Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) -and (Get-Date) -lt $exitDeadline) {
            Start-Sleep -Milliseconds 100
        }
    }

    if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
        throw "Windows denied termination of $Label (PID $ProcessId). Close it in Task Manager or rerun this launcher from an elevated PowerShell window."
    }
}

function Read-LauncherState {
    if (-not (Test-Path -LiteralPath $StateFile)) {
        return $null
    }
    try {
        Get-Content -Raw -LiteralPath $StateFile | ConvertFrom-Json
    }
    catch {
        Write-Warning "Ignoring unreadable launcher state at $StateFile"
        $null
    }
}

function Stop-TrackedProcesses {
    $state = Read-LauncherState
    if (-not $state) {
        return
    }
    if ($state.repo_root -ne $RepoRoot) {
        throw "Launcher state belongs to a different repository: $($state.repo_root)"
    }

    foreach ($serviceName in @("ui", "api")) {
        $service = $state.$serviceName
        if (-not $service) {
            continue
        }
        $tracked = if ($service.PSObject.Properties.Name -contains "processes") {
            @($service.processes)
        }
        elseif ($service.PSObject.Properties.Name -contains "pid") {
            @([pscustomobject]@{ pid = $service.pid; started_at_utc = $service.started_at_utc })
        }
        else {
            @()
        }
        foreach ($trackedProcess in @($tracked | Sort-Object { [int]$_.pid } -Descending)) {
            $processId = [int]$trackedProcess.pid
            $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
            if (-not $process) {
                continue
            }
            $actualStarted = $process.StartTime.ToUniversalTime().ToString("o")
            if ($trackedProcess.started_at_utc -and $actualStarted -ne $trackedProcess.started_at_utc) {
                throw "PID $processId was reused by another process; refusing to stop it automatically."
            }
            Stop-ProcessTree $processId $serviceName
        }
    }

    Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
}

function Test-IsProjectListener([int]$ProcessId, [int]$Port) {
    $commandLine = Get-ProcessCommandLine $ProcessId
    if ($commandLine -and $commandLine -like "*$RepoRoot*") {
        return $true
    }
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($process -and $process.Path -and $process.Path -like "*$RepoRoot*") {
        return $true
    }
    if ($Port -eq $ApiPort -and $commandLine -and $commandLine -match "rv_dashboard\.main|uvicorn.+8080") {
        return $true
    }
    if ($Port -eq $UiPort -and $commandLine -and $commandLine -match "vinext.+dev|vite.+3000") {
        return $true
    }

    # Command-line inspection may be denied by Windows policy. A strong HTTP
    # signature still lets us reclaim an interrupted run without treating an
    # unrelated service on the same port as ours.
    try {
        if ($Port -eq $ApiPort) {
            $health = Invoke-RestMethod -Uri "http://localhost:$ApiPort/health" -TimeoutSec 5
            $properties = @($health.PSObject.Properties.Name)
            if ($health.status -eq "ok" -and $properties -contains "mode" -and $properties -contains "collector_online") {
                return $true
            }
        }
        elseif ($Port -eq $UiPort) {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:$UiPort/" -TimeoutSec 5
            if ($response.StatusCode -eq 200 -and $response.Content -match "RV Systems Dashboard") {
                return $true
            }
        }
    }
    catch {
        return $false
    }
    $false
}

function Clear-RequiredPort([int]$Port, [string]$Label) {
    foreach ($processId in @(Get-ListenerProcessIds $Port)) {
        if ($ForcePortCleanup -or (Test-IsProjectListener $processId $Port)) {
            Stop-ProcessTree $processId "$Label listener on port $Port"
            continue
        }
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        $processName = if ($process) { $process.ProcessName } else { "unknown" }
        throw "Port $Port is occupied by untracked process $processId ($processName). Close it, or rerun with -ForcePortCleanup only after confirming it is stale."
    }
}

function Import-DotEnv([string]$Path) {
    $values = @{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return $values
    }
    $lineNumber = 0
    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $lineNumber++
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }
        if ($line.StartsWith("export ")) {
            $line = $line.Substring(7).Trim()
        }
        $separator = $line.IndexOf("=")
        if ($separator -lt 1) {
            throw "Invalid environment entry at ${Path}:$lineNumber"
        }
        $name = $line.Substring(0, $separator).Trim()
        if ($name -notmatch "^[A-Za-z_][A-Za-z0-9_]*$") {
            throw "Invalid environment key '$name' at ${Path}:$lineNumber"
        }
        $value = $line.Substring($separator + 1).Trim()
        if ($value.Length -ge 2) {
            $first = $value[0]
            $last = $value[$value.Length - 1]
            if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        $values[$name] = $value
    }
    $values
}

function Start-ChildProcess(
    [string]$FilePath,
    [string[]]$ArgumentList,
    [string]$WorkingDirectory,
    [hashtable]$Environment,
    [string]$StandardOutput,
    [string]$StandardError
) {
    $previous = @{}
    try {
        foreach ($name in $Environment.Keys) {
            $previous[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
            [Environment]::SetEnvironmentVariable($name, [string]$Environment[$name], "Process")
        }
        Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory `
            -RedirectStandardOutput $StandardOutput -RedirectStandardError $StandardError `
            -WindowStyle Hidden -PassThru
    }
    finally {
        foreach ($name in $Environment.Keys) {
            [Environment]::SetEnvironmentVariable($name, $previous[$name], "Process")
        }
    }
}

function Resolve-NodeExecutable {
    $command = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $codexNode = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
    if (Test-Path -LiteralPath $codexNode) {
        return $codexNode
    }
    throw "Node.js 22 or later was not found. Install Node.js and ensure node.exe is on PATH."
}

function Wait-ForApi([datetime]$Deadline) {
    $lastError = "no response"
    while ((Get-Date) -lt $Deadline) {
        try {
            $health = Invoke-RestMethod -Uri "http://localhost:$ApiPort/health" -TimeoutSec 3
            if ($health.status -eq "ok") {
                return $health
            }
        }
        catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 500
    }
    throw "API verification timed out: $lastError"
}

function Wait-ForUi([datetime]$Deadline) {
    $lastError = "no response"
    while ((Get-Date) -lt $Deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:$UiPort/" -TimeoutSec 3
            if ($response.StatusCode -eq 200 -and $response.Content -match "RV Systems Dashboard") {
                return
            }
            $lastError = "HTTP $($response.StatusCode) did not contain the dashboard application marker"
        }
        catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 500
    }
    throw "UI verification timed out: $lastError"
}

function Wait-ForListeners([datetime]$Deadline) {
    while ((Get-Date) -lt $Deadline) {
        $apiListeners = @(Get-ListenerProcessIds $ApiPort)
        $uiListeners = @(Get-ListenerProcessIds $UiPort)
        if ($apiListeners.Count -and $uiListeners.Count) {
            return [pscustomobject]@{ api = $apiListeners; ui = $uiListeners }
        }
        Start-Sleep -Milliseconds 250
    }
    throw "The expected listeners on ports $UiPort and $ApiPort were not found. Check the service logs for a port conflict or startup error."
}

function New-TrackedProcess([int]$ProcessId) {
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $process) {
        return $null
    }
    [ordered]@{
        pid = $ProcessId
        started_at_utc = $process.StartTime.ToUniversalTime().ToString("o")
    }
}

function Show-LogTail([string]$Path, [string]$Label) {
    if (Test-Path -LiteralPath $Path) {
        Write-Warning "$Label log tail ($Path):"
        Get-Content -LiteralPath $Path -Tail 20 | Write-Warning
    }
}

function Show-Status {
    $state = Read-LauncherState
    $uiListeners = @(Get-ListenerProcessIds $UiPort)
    $apiListeners = @(Get-ListenerProcessIds $ApiPort)
    Write-Host "Repository: $RepoRoot"
    Write-Host "UI port $UiPort listeners: $($uiListeners -join ', ')"
    Write-Host "API port $ApiPort listeners: $($apiListeners -join ', ')"
    if ($state) {
        $uiTracked = if ($state.ui.PSObject.Properties.Name -contains "processes") { @($state.ui.processes.pid) } else { @($state.ui.pid) }
        $apiTracked = if ($state.api.PSObject.Properties.Name -contains "processes") { @($state.api.processes.pid) } else { @($state.api.pid) }
        Write-Host "Tracked UI PID(s): $($uiTracked -join ', ')"
        Write-Host "Tracked API PID(s): $($apiTracked -join ', ')"
        Write-Host "Logs: $RuntimeRoot"
    }
    else {
        Write-Host "No launcher state is recorded."
    }
}

if ($Action -eq "Status") {
    Show-Status
    exit 0
}

if ($Action -in @("Stop", "Restart")) {
    Stop-TrackedProcesses
    Clear-RequiredPort $UiPort "UI"
    Clear-RequiredPort $ApiPort "API"
    if ($Action -eq "Stop") {
        Write-Step "Development services stopped"
        exit 0
    }
}
elseif (@(Get-ListenerProcessIds $UiPort).Count -or @(Get-ListenerProcessIds $ApiPort).Count) {
    throw "A required port is already in use. Run the launcher with -Action Restart."
}

$python = Join-Path $BackendRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found at $python. Create it and install backend dependencies first."
}
$node = Resolve-NodeExecutable
$vinext = Join-Path $RepoRoot "node_modules\vinext\dist\cli.js"
if (-not (Test-Path -LiteralPath $vinext)) {
    throw "Frontend dependencies are missing. Run npm ci first."
}

New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
$apiOut = Join-Path $RuntimeRoot "api.log"
$apiErr = Join-Path $RuntimeRoot "api-error.log"
$uiOut = Join-Path $RuntimeRoot "ui.log"
$uiErr = Join-Path $RuntimeRoot "ui-error.log"

$apiEnvironment = Import-DotEnv (Join-Path $BackendRoot ".env")
$apiEnvironment["DASHBOARD_API_PORT"] = [string]$ApiPort
$apiEnvironment["DASHBOARD_ORIGINS"] = "http://localhost:$UiPort"
$uiEnvironment = @{
    "NEXT_PUBLIC_DASHBOARD_API_URL" = "http://localhost:$ApiPort"
    "WRANGLER_LOG_PATH" = ".wrangler/wrangler.log"
}

$apiProcess = $null
$uiProcess = $null
try {
    Write-Step "Starting API on http://localhost:$ApiPort"
    $apiProcess = Start-ChildProcess $python @("-m", "uvicorn", "rv_dashboard.main:app", "--host", "0.0.0.0", "--port", [string]$ApiPort) $BackendRoot $apiEnvironment $apiOut $apiErr
    Write-Step "Starting UI on http://localhost:$UiPort"
    $uiProcess = Start-ChildProcess $node @($vinext, "dev", "--host", "0.0.0.0", "--port", [string]$UiPort, "--strictPort") $RepoRoot $uiEnvironment $uiOut $uiErr

    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    $listeners = Wait-ForListeners $deadline
    $health = Wait-ForApi $deadline
    Wait-ForUi $deadline

    $apiProcessIds = @($apiProcess.Id) + @($listeners.api) | Sort-Object -Unique
    $uiProcessIds = @($uiProcess.Id) + @($listeners.ui) | Sort-Object -Unique
    $state = [ordered]@{
        schema_version = 2
        repo_root = $RepoRoot
        api = [ordered]@{ processes = @($apiProcessIds | ForEach-Object { New-TrackedProcess $_ } | Where-Object { $_ }) }
        ui = [ordered]@{ processes = @($uiProcessIds | ForEach-Object { New-TrackedProcess $_ } | Where-Object { $_ }) }
    }
    $temporaryState = "$StateFile.tmp"
    $state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $temporaryState -Encoding UTF8
    Move-Item -LiteralPath $temporaryState -Destination $StateFile -Force

    # Catch immediate child failures (for example, a Windows file-watcher
    # error) before reporting a successful persistent start.
    Start-Sleep -Seconds 2
    if (-not @(Get-ListenerProcessIds $UiPort).Count -or -not @(Get-ListenerProcessIds $ApiPort).Count) {
        throw "A development service exited immediately after startup."
    }

    Write-Step "Ready"
    Write-Host "  UI:        http://localhost:$UiPort"
    Write-Host "  API:       http://localhost:$ApiPort"
    Write-Host "  Mode:      $($health.mode)"
    Write-Host "  Collector: $($health.collector_online)"
    Write-Host "  UI PID(s): $($uiProcessIds -join ', ')"
    Write-Host "  API PID(s): $($apiProcessIds -join ', ')"
    Write-Host "  Logs:      $RuntimeRoot"
    if ($health.mode -eq "live" -and -not $health.collector_online) {
        Write-Warning "The API is healthy, but the RV Whisper collector is currently offline. The dashboard will continue running and retry collection in the background."
    }
}
catch {
    $originalError = $_
    foreach ($processId in @(Get-ListenerProcessIds $UiPort)) {
        try { Stop-ProcessTree $processId "new UI listener" } catch { Write-Warning $_ }
    }
    foreach ($processId in @(Get-ListenerProcessIds $ApiPort)) {
        try { Stop-ProcessTree $processId "new API listener" } catch { Write-Warning $_ }
    }
    if ($uiProcess -and (Get-Process -Id $uiProcess.Id -ErrorAction SilentlyContinue)) {
        try { Stop-ProcessTree $uiProcess.Id "new UI process" } catch { Write-Warning $_ }
    }
    if ($apiProcess -and (Get-Process -Id $apiProcess.Id -ErrorAction SilentlyContinue)) {
        try { Stop-ProcessTree $apiProcess.Id "new API process" } catch { Write-Warning $_ }
    }
    Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
    Show-LogTail $apiErr "API error"
    Show-LogTail $uiErr "UI error"
    throw $originalError
}
