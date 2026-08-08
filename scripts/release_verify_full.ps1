$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ReleasePython = Join-Path $ProjectRoot ".venv-release\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $ReleasePython)) {
    throw "Release virtual environment not found. Run scripts/setup_release_env.ps1 first."
}

function Invoke-ReleasePython {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $ReleasePython @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python command failed: $Arguments" }
}

Set-Location $ProjectRoot
Invoke-ReleasePython -m pytest -q
Invoke-ReleasePython -m build
Invoke-ReleasePython -m twine check dist\*
$Wheel = Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "dist") -Filter "*.whl"
if ($Wheel.Count -ne 1) { throw "Expected exactly one wheel" }
Invoke-ReleasePython scripts/check_release.py $Wheel.FullName
Invoke-ReleasePython scripts/inspect_wheel.py $Wheel.FullName
Invoke-ReleasePython -m pip install --no-deps --force-reinstall $Wheel.FullName
Invoke-ReleasePython -m pip check
$env:CANARY_WHEEL = $Wheel.FullName
Invoke-ReleasePython -m pytest -q
Invoke-ReleasePython scripts/smoke_tool_01_model_info.py
Invoke-ReleasePython scripts/smoke_tool_02_case_qc.py
Invoke-ReleasePython scripts/smoke_tool_03_ct_features.py
Invoke-ReleasePython scripts/smoke_tool_04_pathology_features.py
Invoke-ReleasePython scripts/smoke_tool_05_prediction.py
Invoke-ReleasePython scripts/smoke_tool_06_report.py
Invoke-ReleasePython scripts/smoke_all_six_tools.py --output reports/six_tool_smoke_results.json
Invoke-ReleasePython scripts/smoke_published_style_local_wheel.py --wheel $Wheel.FullName --invariants-only --output reports/lightweight_cross_platform_gate/windows-current.json
Invoke-ReleasePython scripts/build_release_artifacts.py
Invoke-ReleasePython scripts/check_release.py $Wheel.FullName --source-zip (Join-Path $ProjectRoot "crc-lnm-medical-agent-hosted-1.0.19-source.zip")
Write-Host "WINDOWS FULL RELEASE VERIFICATION: PASS"
