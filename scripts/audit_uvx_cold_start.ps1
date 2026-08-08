param(
    [string]$Uv = "uv",
    [string]$AuditPython = "python",
    [string[]]$PythonExecutables = @(),
    [string]$ResultPath = "docs/uvx-cold-start-results.json",
    [switch]$KeepLogs
)

$ErrorActionPreference = "Stop"
$Root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$TempRoot = Join-Path ([IO.Path]::GetTempPath()) ("crc-lnm-uvx-audit-" + [guid]::NewGuid())
$Wheel = @(Get-ChildItem -LiteralPath (Join-Path $Root "dist") -Filter "*.whl")
if ($Wheel.Count -ne 1) { throw "Build first: expected exactly one local wheel in dist" }

# Audited commands: uv --version; uv cache dir; uv python find; uv venv;
# uv pip compile; uv pip install. Cold/warm uvx uses --from with the local wheel.
function Invoke-TimedLogged {
    param([string]$File, [string[]]$Arguments, [string]$Log, [string]$Label)
    $Watch = [Diagnostics.Stopwatch]::StartNew()
    $ErrorActionPreference = "Continue"
    & $File @Arguments *>> $Log
    $Code = $LASTEXITCODE
    $Watch.Stop()
    if ($Code -ne 0) { throw "$Label failed ($Code); see $Log" }
    return [math]::Round($Watch.Elapsed.TotalSeconds, 3)
}

function Invoke-SmokeTimed {
    param([string[]]$Arguments, [string]$Log, [string]$Label)
    $Watch = [Diagnostics.Stopwatch]::StartNew()
    $ErrorActionPreference = "Continue"
    $Output = & $AuditPython (Join-Path $Root "scripts/smoke_tool_05_prediction.py") @Arguments 2>> $Log
    $Code = $LASTEXITCODE
    $Watch.Stop()
    if ($Code -ne 0) { throw "$Label failed ($Code); see $Log" }
    $Report = ($Output -join "`n") | ConvertFrom-Json
    return [ordered]@{
        seconds = [math]::Round($Watch.Elapsed.TotalSeconds, 3)
        initialize_seconds = $Report.timings.initialize_seconds
        console_to_init_seconds = $Report.total_seconds
        peak_rss_bytes = $Report.peak_rss_bytes
        network_connections = @($Report.network_connections)
    }
}

New-Item -ItemType Directory -Path $TempRoot | Out-Null
Push-Location $Root
try {
    $UvVersion = (& $Uv --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "uv --version failed" }
    if ($PythonExecutables.Count -eq 0) {
        $PythonExecutables = @($AuditPython)
    }

    $Results = @()
    foreach ($Runtime in $PythonExecutables) {
        $Runtime = [IO.Path]::GetFullPath($Runtime)
        $Version = (& $Runtime -c "import platform; print(platform.python_version())").Trim()
        if ($LASTEXITCODE -ne 0) { throw "Python version probe failed: $Runtime" }
        $Tag = $Version.Replace(".", "-")
        $RuntimeRoot = Join-Path $TempRoot $Tag
        $PhaseCache = Join-Path $RuntimeRoot "phase-cache"
        $ColdCache = Join-Path $RuntimeRoot "uvx-cache"
        $Venv = Join-Path $RuntimeRoot "phase-venv"
        $Log = Join-Path $RuntimeRoot "verbose-install.log"
        New-Item -ItemType Directory -Path $RuntimeRoot, $PhaseCache, $ColdCache | Out-Null

        $CacheDir = (& $Uv --cache-dir $PhaseCache cache dir 2>> $Log | Out-String).Trim()
        if ($LASTEXITCODE -ne 0) { throw "uv cache dir failed; see $Log" }
        $Discovery = Invoke-TimedLogged $Uv @("--cache-dir", $PhaseCache, "python", "find", "--no-python-downloads", $Runtime) $Log "uv python find"
        $VenvSeconds = Invoke-TimedLogged $Uv @("venv", $Venv, "--python", $Runtime, "--no-python-downloads", "--cache-dir", $PhaseCache) $Log "uv venv"

        $Requirements = Join-Path $RuntimeRoot "wheel.in"
        $Lock = Join-Path $RuntimeRoot "wheel.lock"
        [IO.File]::WriteAllText($Requirements, $Wheel[0].FullName + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
        $Resolve = Invoke-TimedLogged $Uv @("pip", "compile", $Requirements, "--output-file", $Lock, "--python", $Runtime, "--no-python-downloads", "--cache-dir", $PhaseCache, "-v") $Log "uv pip compile"
        $VenvPython = Join-Path $Venv "Scripts/python.exe"
        $Install = Invoke-TimedLogged $Uv @("pip", "install", "--python", $VenvPython, "-r", $Lock, "--no-python-downloads", "--cache-dir", $PhaseCache, "-v") $Log "uv pip install"

        $Console = Join-Path $Venv "Scripts/crc-lnm-medical-agent.exe"
        # Record any transient installer-adjacent connection instead of losing
        # timing data; the release verifier separately enforces zero violations.
        $Direct = Invoke-SmokeTimed @("--command", $Console) $Log "console-to-init"
        $Uvx = Join-Path (Split-Path -Parent $Uv) "uvx.exe"
        if (-not (Test-Path -LiteralPath $Uvx)) { $Uvx = "uvx" }
        $UvxArgs = @(
            "--command", $Uvx,
            "--server-arg=--cache-dir", "--server-arg=$ColdCache",
            "--server-arg=--python", "--server-arg=$Runtime",
            "--server-arg=--no-python-downloads", "--server-arg=--quiet",
            "--server-arg=--from", "--server-arg=$($Wheel[0].FullName)",
            "--server-arg=crc-lnm-medical-agent"
        )
        $Cold = Invoke-SmokeTimed $UvxArgs $Log "cold uvx"
        $Warm = Invoke-SmokeTimed $UvxArgs $Log "warm uvx"

        $Results += [ordered]@{
            python = $Version
            executable = $Runtime
            uv = $UvVersion
            uv_cache_dir = $CacheDir
            python_downloaded = $false
            python_discovery_seconds = $Discovery
            venv_seconds = $VenvSeconds
            resolution_seconds = $Resolve
            install_seconds = $Install
            console_to_init = $Direct
            cold = $Cold
            warm = $Warm
            verbose_log = $Log
        }
    }

    $ResolvedResult = if ([IO.Path]::IsPathRooted($ResultPath)) { $ResultPath } else { Join-Path $Root $ResultPath }
    $Payload = [ordered]@{
        measured_at = [DateTimeOffset]::Now.ToString("o")
        local_wheel = $Wheel[0].FullName
        uv = $UvVersion
        network_note = "Cold/warm uvx may access package indexes; MCP server itself remains STDIO-only."
        runtimes = $Results
    } | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($ResolvedResult, $Payload + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    Write-Host "UVX AUDIT: PASS"
    Write-Host $ResolvedResult
} finally {
    Pop-Location
    if (-not $KeepLogs -and (Test-Path -LiteralPath $TempRoot)) {
        $ResolvedTemp = [IO.Path]::GetFullPath($TempRoot)
        if (-not $ResolvedTemp.StartsWith([IO.Path]::GetFullPath([IO.Path]::GetTempPath()), [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing recursive audit cleanup outside temp root"
        }
        Remove-Item -LiteralPath $ResolvedTemp -Recurse -Force
    }
}
