# Start SatQuery AI on this laptop: checks first, then one server for the workspace and the API. Press Ctrl+C to stop.
# Usage: .\start-satquery.ps1 [-Setup] [-Rebuild] [-FineTuned] [-Accounts] [-NoBrowser] [-Port <n>]
#   -Setup      first time on this laptop: create backend\.venv and install the Python and Node packages
#   -Rebuild    rebuild the workspace even if the last build looks up to date
#   -FineTuned  also start the fine-tuned Qwen2-VL (finetune\serve.py, 4-bit, needs the NVIDIA GPU) and answer
#               vision questions with it instead of Groq
#   -Accounts   keep Supabase sign-in on (off by default, like the public site: the built-in mailer only reaches
#               members of the Supabase organisation)
#   -NoBrowser  do not open the browser
#   -Port       where to serve it (default 7860, so it runs beside TripSathi on 8000)
# The checks print OK or NOT OK only; they never print a value from backend\.env.

param([switch]$Setup, [switch]$Rebuild, [switch]$FineTuned, [switch]$Accounts, [switch]$NoBrowser, [int]$Port = 7860)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$dist = Join-Path $frontend 'dist'
$python = Join-Path $backend '.venv\Scripts\python.exe'
$logs = Join-Path $backend 'run-logs'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$port = $Port
$modelPort = 8001
$servePython = Join-Path $HOME '.satquery-serve\Scripts\python.exe'
$modelDir = Join-Path $root 'models\satquery-qwen2vl-rsvqa'
$url = "http://localhost:$port"

function Fail([string]$why, [string]$fix = '') {
    Write-Host "NOT OK: $why" -ForegroundColor Red
    if ($fix) { Write-Host "  Fix: $fix" -ForegroundColor Yellow }
    Write-Host 'SatQuery was not started.' -ForegroundColor Red
    exit 1
}

function Run-Logged([string]$what, [string]$command, [string]$log, [string]$where) {
    Push-Location $where
    try {
        cmd /c "$command > `"$log`" 2>&1"
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($code -ne 0) { Fail "$what failed" "read its log: $log" }
}

New-Item -ItemType Directory -Force -Path $logs | Out-Null

Write-Host ''
Write-Host 'SatQuery AI: checking before the start' -ForegroundColor Cyan

if ($Setup) {
    Write-Host '0. First-time set-up (a few minutes)'
    if (-not (Test-Path $python)) {
        $launcher = Get-Command py -ErrorAction SilentlyContinue
        $creator = if ($null -ne $launcher) { 'py -3.13' } else { 'python' }
        Run-Logged 'Creating backend\.venv' "$creator -m venv .venv" (Join-Path $logs "setup-venv-$stamp.log") $backend
    }
    Run-Logged 'Installing the Python packages' '.venv\Scripts\python.exe -m pip install -r requirements-lock.txt' (Join-Path $logs "setup-pip-$stamp.log") $backend
    Run-Logged 'Installing the Node packages' 'npm ci' (Join-Path $logs "setup-npm-$stamp.log") $frontend
    Write-Host '   OK: the Python and Node packages are installed'
}

Write-Host '1. The tools'
if (-not (Test-Path $python)) { Fail 'backend\.venv is missing' 'double-click start-satquery.cmd once with set-up: run  .\start-satquery.ps1 -Setup' }
if ($null -eq (Get-Command node -ErrorAction SilentlyContinue)) { Fail 'Node.js is not installed or not on PATH' 'install Node.js 22 LTS from nodejs.org, then start again' }
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) { Fail 'frontend\node_modules is missing' 'run  .\start-satquery.ps1 -Setup' }
# A failed import writes to stderr, which Windows PowerShell would turn into a terminating error here.
$ErrorActionPreference = 'Continue'
& $python -c "import fastapi, uvicorn, numpy" 2>$null | Out-Null
$corePackages = $LASTEXITCODE
& $python -c "import rasterio, rasterio.vrt" 2>$null | Out-Null
$rasterio = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($corePackages -ne 0) { Fail 'the Python packages are incomplete' 'run  .\start-satquery.ps1 -Setup' }
if ($rasterio -eq 0) {
    Write-Host '   OK: Python, Node.js, the packages and rasterio (GDAL)'
} else {
    Write-Host '   OK: Python, Node.js and the packages'
    Write-Host '   NOTE: rasterio did not load, so questions without an upload cannot fetch imagery (uploads still work)' -ForegroundColor Yellow
}

Write-Host '2. The settings (backend\.env)'
$values = @{}
$envFile = Join-Path $backend '.env'
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)$') {
            $values[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
        }
    }
} else {
    Write-Host '   NOTE: there is no backend\.env, so everything runs on the defaults' -ForegroundColor Yellow
}
if ([string]::IsNullOrWhiteSpace($values['SATQUERY_AGENT_API_KEY'])) {
    Write-Host '   Questions: read by the offline rules (no Groq key set)'
} else {
    Write-Host '   Questions: read by the Groq model (key set)'
}
$vqaOn = @('true', '1', 'yes', 'on') -contains ("$($values['SATQUERY_VQA_ENABLED'])".ToLower())
if ($FineTuned) {
    Write-Host '   Vision questions: the fine-tuned Qwen2-VL on this laptop (-FineTuned)'
} elseif ($vqaOn) {
    Write-Host '   Vision questions: on, answered by the hosted model'
} else {
    Write-Host '   Vision questions: off (set SATQUERY_VQA_ENABLED=true, or start with -FineTuned)'
}
if ($Accounts -and -not [string]::IsNullOrWhiteSpace($values['SATQUERY_SUPABASE_URL'])) {
    Write-Host '   Accounts: Supabase sign-in on (-Accounts)'
} else {
    Write-Host '   Accounts: off, the workspace opens without sign-in'
}

Write-Host '3. The ports'
$ports = @($port)
if ($FineTuned) { $ports += $modelPort }
foreach ($p in $ports) {
    if ($null -ne (Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue)) {
        Fail "port $p is in use" 'close the other SatQuery window (or whatever uses it) and start again'
    }
}
Write-Host "   OK: $($ports -join ' and ') free"

Write-Host '4. The workspace build'
$marker = Join-Path $dist '.satquery-build'
$sources = @('src', 'public', 'index.html', 'package.json', 'package-lock.json', 'vite.config.ts') | ForEach-Object { Join-Path $frontend $_ }
$newest = Get-ChildItem $sources -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$fresh = (Test-Path $marker) -and (Test-Path (Join-Path $dist 'index.html')) -and ((Get-Item $marker).LastWriteTime -gt $newest.LastWriteTime)
if ($Rebuild -or -not $fresh) {
    Write-Host '   Building (about a minute)...'
    # The workspace calls the API on its own origin; a leftover setting must not point it elsewhere.
    Get-ChildItem Env: | Where-Object { $_.Name -like 'VITE_*' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
    Run-Logged 'The workspace build' 'npm run build' (Join-Path $logs "build-$stamp.log") $frontend
    Set-Content -Path $marker -Value $stamp -Encoding ascii
    Write-Host '   OK: built'
} else {
    Write-Host '   OK: the last build is up to date'
}

if ($FineTuned) {
    Write-Host '5. The fine-tuned model'
    if (-not (Test-Path $servePython)) { Fail "$servePython is missing" 'set up the serving environment as in finetune\README.md, section "4-bit on a GTX 1650"' }
    if (-not (Test-Path (Join-Path $modelDir 'adapter'))) { Fail 'models\satquery-qwen2vl-rsvqa is missing' 'unzip satquery-qwen2vl-rsvqa.zip from the Kaggle run into models\' }
    Write-Host '   OK: the serving environment and the model files'
}

Write-Host ''
Write-Host 'SatQuery AI: starting' -ForegroundColor Cyan
$backendLog = Join-Path $logs "backend-$stamp.log"
$modelLog = Join-Path $logs "model-$stamp.log"
$server = $null
$model = $null
$setNames = @()

function Set-RunEnv([string]$name, [string]$value) {
    Set-Item -Path "Env:$name" -Value $value
    $script:setNames += $name
}

try {
    if ($FineTuned) {
        Write-Host '   Loading the fine-tuned model on the GPU (about a minute)...'
        $model = Start-Process -FilePath $servePython -WorkingDirectory $root -WindowStyle Hidden -PassThru `
            -ArgumentList @('finetune\serve.py', '--model-dir', "`"$modelDir`"", '--port', "$modelPort", '--load-in-4bit') `
            -RedirectStandardError $modelLog -RedirectStandardOutput "$modelLog.out"
        $up = $false
        for ($second = 0; $second -lt 300 -and -not $up; $second += 2) {
            Start-Sleep -Seconds 2
            if ($model.HasExited) { Fail 'the fine-tuned model stopped while loading' "read its log: $modelLog" }
            try {
                $up = (Invoke-WebRequest -Uri "http://127.0.0.1:$modelPort/v1/models" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200
            } catch {
                $up = $false
            }
        }
        if (-not $up) { Fail 'the fine-tuned model did not answer within 5 minutes' "read its log: $modelLog" }
        Write-Host '   OK: the fine-tuned model answers'
        Set-RunEnv 'SATQUERY_VQA_ENABLED' 'true'
        Set-RunEnv 'SATQUERY_VQA_PROVIDER' 'hosted'
        Set-RunEnv 'SATQUERY_VQA_BASE_URL' "http://127.0.0.1:$modelPort/v1"
        Set-RunEnv 'SATQUERY_VQA_MODEL' 'satquery-qwen2vl-rsvqa'
        Set-RunEnv 'SATQUERY_VQA_BENCHMARK_REPORT' (Join-Path $modelDir 'benchmark_report.json')
    }
    Set-RunEnv 'SATQUERY_FRONTEND_DIST' $dist
    if (-not $Accounts) {
        # A blank value wins over backend\.env (a real environment variable always does) and reads as "off".
        Set-RunEnv 'SATQUERY_SUPABASE_URL' ' '
    }

    $server = Start-Process -FilePath $python -WorkingDirectory $backend -WindowStyle Hidden -PassThru `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$port") `
        -RedirectStandardError $backendLog -RedirectStandardOutput "$backendLog.out"

    $ready = $false
    for ($second = 0; $second -lt 60 -and -not $ready; $second++) {
        Start-Sleep -Seconds 1
        if ($server.HasExited) { Fail 'the server stopped while starting' "read its log: $backendLog" }
        try {
            $health = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/health" -UseBasicParsing -TimeoutSec 5
            $page = Invoke-WebRequest -Uri "http://127.0.0.1:$port/" -UseBasicParsing -TimeoutSec 5
            $ready = ($health.StatusCode -eq 200) -and ($page.StatusCode -eq 200)
        } catch {
            $ready = $false
        }
    }
    if (-not $ready) { Fail 'SatQuery did not answer within 60 s' "read its log: $backendLog" }

    Write-Host ''
    Write-Host "SatQuery AI is running: $url" -ForegroundColor Green
    Write-Host "API documentation: $url/docs"
    Write-Host "The server log is $backendLog"
    Write-Host 'Press Ctrl+C here to stop SatQuery.'
    Write-Host ''
    if (-not $NoBrowser) { Start-Process $url }
    Get-Content -Path $backendLog -Wait
} finally {
    if ($null -ne $server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
    if ($null -ne $model -and -not $model.HasExited) { Stop-Process -Id $model.Id -Force }
    foreach ($name in $setNames) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
    Write-Host 'SatQuery stopped.'
}
