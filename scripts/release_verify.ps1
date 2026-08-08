$ErrorActionPreference = "Stop"
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$ReleasePython = Join-Path $ProjectRoot ".venv-release\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $ReleasePython -PathType Leaf)) {
    throw "Release virtual environment not found. Run scripts/setup_release_env.ps1 first."
}
$Root = $ProjectRoot
$TempRoot = Join-Path ([IO.Path]::GetTempPath()) ("crc-lnm-release-" + [guid]::NewGuid())
$Version = "1.0.11"
$PythonVersion = (& $ReleasePython -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect release interpreter: $ReleasePython (exit code $LASTEXITCODE)"
}
$PythonParts = $PythonVersion.Split(".")
$PythonMinor = "$($PythonParts[0]).$($PythonParts[1])"
$SupportedPython = @("3.10", "3.11", "3.12")
if ($PythonMinor -notin $SupportedPython) {
    throw "Unsupported release interpreter: $ReleasePython ($PythonVersion). Expected Python 3.10, 3.11, or 3.12."
}
Write-Host "Release Python executable: $ReleasePython"
Write-Host "Release Python version: $PythonVersion"

# Required gates: python -m build; python -m twine check; python -m pytest -q
function Invoke-Python {
    param([string[]]$Arguments, [string]$Label)
    Write-Host "==> $Label"
    & $ReleasePython @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Label failed with exit code $LASTEXITCODE" }
}

function Remove-WorkspaceTree {
    param([string]$Path)
    $Resolved = [IO.Path]::GetFullPath($Path)
    if (-not $Resolved.StartsWith($Root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing recursive removal outside workspace: $Resolved"
    }
    if (Test-Path -LiteralPath $Resolved) { Remove-Item -LiteralPath $Resolved -Recurse -Force }
}

Push-Location $Root
try {
    Invoke-Python -Arguments @("--version") -Label "Python discovery"
    Invoke-Python -Arguments @("-c", "import build, twine, pytest, psutil") -Label "Verification dependencies"

    Remove-WorkspaceTree (Join-Path $Root "build")
    Remove-WorkspaceTree (Join-Path $Root "dist")
    Remove-WorkspaceTree (Join-Path $Root ".pytest_cache")
    foreach ($OldReleaseFile in @("crc-lnm-medical-agent-$Version-source.zip", "RELEASE_CHECKSUMS.sha256")) {
        $OldPath = Join-Path $Root $OldReleaseFile
        if (Test-Path -LiteralPath $OldPath) { Remove-Item -LiteralPath $OldPath -Force }
    }
    Get-ChildItem -LiteralPath (Join-Path $Root "src") -Directory -Filter "*.egg-info" |
        ForEach-Object { Remove-WorkspaceTree $_.FullName }
    Get-ChildItem -LiteralPath $Root -Directory -Recurse -Force |
        Where-Object { $_.Name -eq "__pycache__" } |
        Sort-Object FullName -Descending |
        ForEach-Object { Remove-WorkspaceTree $_.FullName }
    Get-ChildItem -LiteralPath $Root -File -Recurse -Filter "*.pyc" |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

    Invoke-Python -Arguments @("-m", "build") -Label "python -m build"
    $Artifacts = @(Get-ChildItem -LiteralPath (Join-Path $Root "dist") -File |
        Where-Object { $_.Extension -in @(".whl", ".gz") } | Select-Object -ExpandProperty FullName)
    if ($Artifacts.Count -ne 2) { throw "Expected exactly one wheel and one sdist" }
    Invoke-Python -Arguments (@("-m", "twine", "check") + $Artifacts) -Label "python -m twine check"

    $Wheel = @(Get-ChildItem -LiteralPath (Join-Path $Root "dist") -Filter "*.whl")
    if ($Wheel.Count -ne 1) { throw "Expected exactly one wheel" }
    Invoke-Python -Arguments @("scripts/check_release.py", $Wheel[0].FullName) -Label "scripts/check_release.py"
    Invoke-Python -Arguments @("scripts/inspect_wheel.py", $Wheel[0].FullName) -Label "scripts/inspect_wheel.py"

    $env:CANARY_WHEEL = $Wheel[0].FullName
    Invoke-Python -Arguments @("-m", "pytest", "-q") -Label "python -m pytest -q"

    New-Item -ItemType Directory -Path $TempRoot | Out-Null
    $Venv = Join-Path $TempRoot "wheel-only"
    Invoke-Python -Arguments @("-m", "venv", $Venv) -Label "Create wheel-only environment"
    $VenvPython = Join-Path $Venv "Scripts/python.exe"
    & $VenvPython -m pip install --disable-pip-version-check --force-reinstall $Wheel[0].FullName pytest psutil
    if ($LASTEXITCODE -ne 0) { throw "Wheel-only installation failed" }
    $env:CANARY_INSTALLED = "1"
    $env:CANARY_CONSOLE = Join-Path $Venv "Scripts/crc-lnm-medical-agent.exe"
    & $VenvPython -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Wheel-only test suite failed" }

    $ArbitraryCwd = Join-Path $TempRoot "arbitrary-cwd"
    New-Item -ItemType Directory -Path $ArbitraryCwd | Out-Null
    $SmokeJson = & $VenvPython scripts/smoke_stdio.py --cwd $ArbitraryCwd --command $env:CANARY_CONSOLE
    if ($LASTEXITCODE -ne 0) { throw "scripts/smoke_stdio.py failed" }
    $Smoke = $SmokeJson | ConvertFrom-Json
    if (($Smoke.tools -join ",") -ne "describe_deployment,healthcheck") { throw "Unexpected tool list" }
    if ($Smoke.healthcheck.version -ne $Version) { throw "Unexpected healthcheck version" }
    if ($Smoke.leaked_child_processes.Count -ne 0) { throw "Leaked child process" }
    if (@(Get-ChildItem -LiteralPath $ArbitraryCwd -Force).Count -ne 0) { throw "Arbitrary CWD was mutated" }

    $Stage = Join-Path $TempRoot "source-stage"
    New-Item -ItemType Directory -Path $Stage | Out-Null
    foreach ($File in @("pyproject.toml", "README.md", "modelscope-mcp.json")) {
        Copy-Item -LiteralPath (Join-Path $Root $File) -Destination $Stage
    }
    foreach ($Folder in @("src/crc_lnm_mcp", "scripts", "tests", "docs")) {
        $Destination = Join-Path $Stage $Folder
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
        Get-ChildItem -LiteralPath (Join-Path $Root $Folder) -File |
            Where-Object { $_.Extension -in @(".py", ".ps1", ".md") } |
            Copy-Item -Destination $Destination
    }
    $SourceZip = Join-Path $Root "crc-lnm-medical-agent-$Version-source.zip"
    Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $SourceZip -CompressionLevel Optimal
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [IO.Compression.ZipFile]::OpenRead($SourceZip)
    try {
        $Names = @($Archive.Entries | ForEach-Object { $_.FullName.ToLowerInvariant() })
        foreach ($Forbidden in @("wei_multimodal", "__pycache__", ".pyc", "models/", "data/")) {
            if ($Names | Where-Object { $_.Contains($Forbidden) }) { throw "Forbidden source.zip entry: $Forbidden" }
        }
    } finally { $Archive.Dispose() }

    $ChecksumPath = Join-Path $Root "RELEASE_CHECKSUMS.sha256"
    $ChecksumInputs = @(
        Get-ChildItem -LiteralPath (Join-Path $Root "dist") -File |
            Where-Object { $_.Extension -in @(".whl", ".gz") }
        Get-Item -LiteralPath $SourceZip
    )
    $ChecksumLines = $ChecksumInputs |
        Sort-Object Name |
        ForEach-Object { $Hash = Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName; "$($Hash.Hash.ToLowerInvariant())  $($_.Name)" }
    [IO.File]::WriteAllLines($ChecksumPath, $ChecksumLines, [Text.UTF8Encoding]::new($false))
    if ($ChecksumLines.Count -ne 3) { throw "Expected checksums for wheel, sdist, and source.zip" }

    Write-Host "LOCAL RELEASE VERIFICATION: PASS"
} finally {
    Pop-Location
    Remove-Item Env:CANARY_WHEEL -ErrorAction SilentlyContinue
    Remove-Item Env:CANARY_INSTALLED -ErrorAction SilentlyContinue
    Remove-Item Env:CANARY_CONSOLE -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $TempRoot) {
        $ResolvedTemp = [IO.Path]::GetFullPath($TempRoot)
        if (-not $ResolvedTemp.StartsWith([IO.Path]::GetFullPath([IO.Path]::GetTempPath()), [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing recursive temp cleanup outside temp root"
        }
        Remove-Item -LiteralPath $ResolvedTemp -Recurse -Force
    }
}
