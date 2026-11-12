# XBow CyberRange platform manager (Windows) - background service mode.
# Companion of xbow.sh (Linux/macOS); same subcommands, same safety rules:
#   - start refuses occupied ports (double-start keeps old code running silently)
#   - stop validates the process command line before killing (no blind kill)
#   - pid files: backend.pid / frontend.pid (repo root); logs rotate to *.old
#
# xbow.bat is a thin wrapper around this file (cmd / double-click friendly).

param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Rest)

$ErrorActionPreference = "Stop"

$Root            = $PSScriptRoot
$BackendDir      = Join-Path $Root "backend"
$FrontendDir     = Join-Path $Root "frontend"
$VenvDir         = Join-Path $BackendDir ".venv"
$BackendLog      = Join-Path $BackendDir "backend.log"
$BackendErrLog   = Join-Path $BackendDir "backend.err.log"
$FrontendLog     = Join-Path $FrontendDir "frontend.log"
$FrontendErrLog  = Join-Path $FrontendDir "frontend.err.log"
$BackendPidFile  = Join-Path $Root "backend.pid"
$FrontendPidFile = Join-Path $Root "frontend.pid"
$BackendPort     = 8000
$FrontendPort    = 5173

$PythonExe = "python"
$Mode      = "dev"
$UseVenv   = $true
$NoBuild   = $false

# ---------- output helpers ----------
function Write-Info    { param($m) Write-Host "[info] $m" }
function Write-Okay    { param($m) Write-Host "[ok] $m" -ForegroundColor Green }
function Write-WarnMsg { param($m) Write-Host "[warn] $m" -ForegroundColor Yellow }
function Die           { param($m) Write-Host "[error] $m" -ForegroundColor Red; exit 1 }

function Show-Usage {
Write-Host @"
XBow CyberRange platform manager (Windows, background mode)

Usage: .\xbow.bat <command> [options]

Commands:
  start      Start backend (and frontend in dev mode) in the background
  stop       Stop background services (validates PID first, never blind-kills)
  restart    stop + start
  status     Show running state of backend / frontend
  logs       Show logs: .\xbow.bat logs [backend|frontend] [-f|--follow]
  install    Only install dependencies, do not start anything

Options for start/restart:
  --prod         Production mode: build frontend, backend runs without --reload
  --no-build     (with --prod) skip frontend build
  --no-venv      Do not use a Python virtualenv

Default command is "start" in dev mode.
"@
}

# ---------- arg parsing ----------
$Command = "start"
if ($Rest -and $Rest.Count -gt 0) { $Command = $Rest[0] }
$valid = @("start","stop","restart","status","logs","install","-h","--help","help")
if ($valid -notcontains $Command) { Die "unknown command: $Command (try --help)" }
if ($Command -eq "-h" -or $Command -eq "--help" -or $Command -eq "help") { Show-Usage; exit 0 }

$opts = @()
if ($Rest -and $Rest.Count -gt 1) { $opts = @($Rest | Select-Object -Skip 1) }
foreach ($o in $opts) {
  switch ($o) {
    "--prod"     { $Mode = "prod" }
    "--no-venv"  { $UseVenv = $false }
    "--no-build" { $NoBuild = $true }
    "-f"         { }
    "--follow"   { }
    "backend"    { }
    "frontend"   { }
    default      { Die "unknown option: $o (try --help)" }
  }
}
$Follow     = (@($opts) -contains "-f") -or (@($opts) -contains "--follow")
$LogsTarget = "all"
if (@($opts) -contains "backend")  { $LogsTarget = "backend" }
elseif (@($opts) -contains "frontend") { $LogsTarget = "frontend" }

# ---------- native command helpers (avoid PS5.1 stderr+EAP traps) ----------
function Invoke-Native([string]$exe, [string[]]$arguments) {
  $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
  try { & $exe @arguments 2>$null | Out-Null } catch { }
  finally { $ErrorActionPreference = $prev }
  return $LASTEXITCODE
}

function Invoke-Capture([string]$exe, [string[]]$arguments) {
  $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
  try { $out = (& $exe @arguments 2>&1 | Out-String).Trim() } catch { $out = "" }
  finally { $ErrorActionPreference = $prev }
  return $out
}

# ---------- process helpers ----------
function Get-ListenPid([int]$port) {
  try {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop
    if ($c) { return @($c)[0].OwningProcess }
  } catch { }
  return 0
}

function Test-PidMatches([int]$procId, [string]$marker) {
  if ($procId -le 0) { return $false }
  try { Get-Process -Id $procId -ErrorAction Stop | Out-Null } catch { return $false }
  $cmdline = $null
  try {
    $cmdline = (Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction Stop).CommandLine
  } catch { }
  if (-not $cmdline) { return $false }
  return ($cmdline -match $marker)
}

function Get-PidFromFile([string]$f) {
  if (Test-Path $f) {
    $v = (Get-Content $f -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($v) { try { return [int]$v } catch { return 0 } }
  }
  return 0
}

function Test-HealthOk([int]$port) {
  $url = "http://127.0.0.1:$port/api/health"
  $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
  if ($curl) {
    return ((Invoke-Native "curl.exe" @("-s","-o","NUL","--noproxy","*","-m","2",$url)) -eq 0)
  }
  try { Invoke-RestMethod -Uri $url -TimeoutSec 2 | Out-Null; return $true } catch { return $false }
}

function Rotate-Log([string]$path) {
  if (Test-Path $path) {
    Remove-Item "$path.old" -Force -ErrorAction SilentlyContinue
    Move-Item $path "$path.old" -Force -ErrorAction SilentlyContinue
  }
}

# ---------- prerequisites ----------
function Resolve-Python {
  if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Die "python not found in PATH. Install Python 3.10+ first."
  }
  if ((Invoke-Native "python" @("-c","import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)")) -ne 0) {
    Die "Python >= 3.10 required (found: $(Invoke-Capture "python" @("-V")))"
  }
  Write-Okay "Python: $(Invoke-Capture "python" @("-V"))"
}

function Check-Docker {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Die "docker not found in PATH. Install Docker Desktop."
  }
  if ((Invoke-Native "docker" @("info")) -ne 0) {
    Die "Cannot reach Docker daemon. Start Docker Desktop."
  }
  Write-Okay "Docker daemon reachable."
}

function Check-Node {
  if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Die "Node.js not found. Install Node.js 18+."
  }
  $nv = Invoke-Capture "node" @("-v")
  $major = 0
  try { $major = [int](($nv -replace '^v','') -split '\.')[0] } catch { }
  if ($major -lt 18) { Die "Node.js >= 18 required (found $nv)" }
  if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Die "npm not found. Install Node.js 18+." }
  Write-Okay "Node: $nv, npm $(Invoke-Capture "npm" @("-v"))"
}

# ---------- setup ----------
function Setup-Backend {
  if ($UseVenv) {
    if (-not (Test-Path $VenvDir)) {
      Write-Info "creating virtualenv at backend\.venv ..."
      if ((Invoke-Native "python" @("-m","venv",$VenvDir)) -ne 0) { Die "failed to create virtualenv." }
    }
    $script:PythonExe = Join-Path $VenvDir "Scripts\python.exe"
    if (-not (Test-Path $PythonExe)) { Die "venv python not found at $PythonExe" }
  } else {
    $script:PythonExe = "python"
  }
  if ((Invoke-Native $PythonExe @("-c","import fastapi, docker, mcp")) -ne 0) {
    Write-Info "installing backend dependencies ..."
    Invoke-Native $PythonExe @("-m","pip","install","--upgrade","pip") | Out-Null
    if ((Invoke-Native $PythonExe @("-m","pip","install","-r",(Join-Path $BackendDir "requirements.txt"))) -ne 0) {
      Die "pip install failed."
    }
  } else {
    Write-Okay "backend dependencies present."
  }
  $envFile = Join-Path $BackendDir ".env"
  if (-not (Test-Path $envFile) -and (Test-Path (Join-Path $BackendDir ".env.example"))) {
    Copy-Item (Join-Path $BackendDir ".env.example") $envFile
    Write-WarnMsg "created backend\.env from .env.example."
    Write-WarnMsg "For production, edit SECRET_KEY and the admin password!"
  }
}

function Setup-Frontend {
  if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Write-Info "installing frontend dependencies ..."
    Push-Location $FrontendDir
    try { Invoke-Native "npm.cmd" @("install") | Out-Null }
    finally { Pop-Location }
  } else {
    Write-Okay "frontend dependencies present."
  }
}

# ---------- start ----------
function Start-Backend {
  $owner = Get-ListenPid $BackendPort
  if ($owner -gt 0) {
    $procId = Get-PidFromFile $BackendPidFile
    if ($procId -gt 0 -and (Test-PidMatches $procId "uvicorn")) {
      Die "backend already running (pid $procId). Use .\xbow.bat restart or stop."
    }
    Write-WarnMsg "port $BackendPort is occupied by another process (pid $owner):"
    Write-Host (Invoke-Capture "tasklist" @("/FI","PID eq $owner"))
    Die "refusing to start backend on an occupied port."
  }
  Write-Info "starting backend (uvicorn @ 0.0.0.0:$BackendPort, mode=$Mode) in background ..."
  Rotate-Log $BackendLog
  Rotate-Log $BackendErrLog
  $uvArgs = @("-m","uvicorn","app.main:app")
  if ($Mode -eq "dev") { $uvArgs += "--reload" }
  $uvArgs += @("--host","0.0.0.0","--port","$BackendPort")
  $p = Start-Process -FilePath $PythonExe -ArgumentList $uvArgs -WorkingDirectory $BackendDir `
      -WindowStyle Hidden -RedirectStandardOutput $BackendLog -RedirectStandardError $BackendErrLog -PassThru
  Set-Content -Path $BackendPidFile -Value $p.Id
  Start-Sleep -Seconds 2
  if (-not (Get-Process -Id $p.Id -ErrorAction SilentlyContinue)) {
    Die "backend exited right after start; see $BackendErrLog"
  }
  for ($i = 0; $i -lt 30; $i++) {
    if (-not (Get-Process -Id $p.Id -ErrorAction SilentlyContinue)) {
      Die "backend exited during startup; see $BackendErrLog"
    }
    if (Test-HealthOk $BackendPort) { Write-Okay "backend ready (pid $($p.Id))."; return }
    Start-Sleep -Seconds 1
  }
  Write-WarnMsg "backend not ready after 30s; check: .\xbow.bat logs backend -f"
}

function Start-Frontend {
  $owner = Get-ListenPid $FrontendPort
  if ($owner -gt 0) {
    $procId = Get-PidFromFile $FrontendPidFile
    if ($procId -gt 0 -and (Test-PidMatches $procId "npm|vite|node")) {
      Die "frontend already running (pid $procId). Use .\xbow.bat restart or stop."
    }
    Write-WarnMsg "port $FrontendPort is occupied by another process (pid $owner):"
    Write-Host (Invoke-Capture "tasklist" @("/FI","PID eq $owner"))
    Die "refusing to start frontend on an occupied port."
  }
  Write-Info "starting frontend (vite @ 0.0.0.0:$FrontendPort) in background ..."
  Rotate-Log $FrontendLog
  Rotate-Log $FrontendErrLog
  $npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
  if (-not $npm) { $npm = (Get-Command npm -ErrorAction Stop).Source }
  $p = Start-Process -FilePath $npm -ArgumentList @("run","dev","--","--host","0.0.0.0","--port","$FrontendPort") `
      -WorkingDirectory $FrontendDir -WindowStyle Hidden `
      -RedirectStandardOutput $FrontendLog -RedirectStandardError $FrontendErrLog -PassThru
  Set-Content -Path $FrontendPidFile -Value $p.Id
  Start-Sleep -Seconds 2
  if (-not (Get-Process -Id $p.Id -ErrorAction SilentlyContinue)) {
    Die "frontend exited right after start; see $FrontendErrLog"
  }
  for ($i = 0; $i -lt 30; $i++) {
    if (-not (Get-Process -Id $p.Id -ErrorAction SilentlyContinue)) {
      Die "frontend exited during startup; see $FrontendErrLog"
    }
    if ((Get-ListenPid $FrontendPort) -gt 0) { Write-Okay "frontend ready (pid $($p.Id))."; return }
    Start-Sleep -Seconds 1
  }
  Write-WarnMsg "frontend not listening after 30s; check: .\xbow.bat logs frontend -f"
}

# ---------- stop ----------
function Stop-One([string]$pidFile, [string]$marker, [string]$name, [int]$port) {
  $procId = Get-PidFromFile $pidFile
  if ($procId -gt 0 -and (Test-PidMatches $procId $marker)) {
    Write-Info "stopping $name (pid $procId) ..."
    # Windows has no SIGTERM; validated above -> force-kill the whole tree
    # (parent python + uvicorn reload child / npm cmd shim + vite node child).
    Invoke-Native "taskkill" @("/PID","$procId","/T","/F") | Out-Null
    Start-Sleep -Seconds 1
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    if (Get-Process -Id $procId -ErrorAction SilentlyContinue) {
      Write-WarnMsg "$name (pid $procId) survived taskkill; check manually."
    } else {
      Write-Okay "$name stopped."
    }
  } else {
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    $owner = Get-ListenPid $port
    if ($owner -gt 0) {
      Write-WarnMsg "$name : pid file stale/absent and port $port is held by an unknown process (pid $owner) - NOT killing it"
    } else {
      Write-Okay "$name not running."
    }
  }
}

# ---------- commands ----------
function Invoke-Stop {
  Stop-One $BackendPidFile  "uvicorn"       "backend"  $BackendPort
  Stop-One $FrontendPidFile "npm|vite|node" "frontend" $FrontendPort
}

function Invoke-Status {
  $procId = Get-PidFromFile $BackendPidFile
  if ($procId -gt 0 -and (Test-PidMatches $procId "uvicorn")) {
    Write-Okay "backend : running (pid $procId)"
  } elseif ((Get-ListenPid $BackendPort) -gt 0) {
    Write-WarnMsg "backend : pid file stale/absent, but port $BackendPort is held by an unknown process (pid $(Get-ListenPid $BackendPort))"
  } else {
    Write-Info "backend : stopped"
  }
  $procId = Get-PidFromFile $FrontendPidFile
  if ($procId -gt 0 -and (Test-PidMatches $procId "npm|vite|node")) {
    Write-Okay "frontend: running (pid $procId)"
  } elseif ((Get-ListenPid $FrontendPort) -gt 0) {
    Write-WarnMsg "frontend: pid file stale/absent, but port $FrontendPort is held by an unknown process (pid $(Get-ListenPid $FrontendPort))"
  } else {
    Write-Info "frontend: stopped"
  }
  Write-Info "logs: $BackendLog / $FrontendLog  (.\xbow.bat logs -f)"
}

function Invoke-Logs {
  switch ($LogsTarget) {
    "backend" {
      if (-not (Test-Path $BackendLog)) { Write-WarnMsg "no log yet: $BackendLog"; return }
      if ($Follow) { Get-Content $BackendLog -Tail 50 -Wait } else { Get-Content $BackendLog -Tail 50 }
    }
    "frontend" {
      if (-not (Test-Path $FrontendLog)) { Write-WarnMsg "no log yet: $FrontendLog"; return }
      if ($Follow) { Get-Content $FrontendLog -Tail 50 -Wait } else { Get-Content $FrontendLog -Tail 50 }
    }
    default {
      if ($Follow) {
        $both = @($BackendLog, $FrontendLog) | Where-Object { Test-Path $_ }
        if (-not $both) { Write-WarnMsg "no logs yet."; return }
        Get-Content $both -Tail 50 -Wait
      } else {
        foreach ($f in @($BackendLog, $FrontendLog)) {
          Write-Host "===== $f ====="
          if (Test-Path $f) { Get-Content $f -Tail 50 } else { Write-Host "(no log yet)" }
        }
      }
    }
  }
}

function Invoke-Start {
  Resolve-Python
  Check-Docker
  Setup-Backend
  if ($Mode -eq "dev") {
    Check-Node
    Setup-Frontend
  } elseif (-not $NoBuild) {
    Check-Node
    Setup-Frontend
    Write-Info "building frontend (production) ..."
    Push-Location $FrontendDir
    try {
      if ((Invoke-Native "npm.cmd" @("run","build")) -ne 0) { Die "frontend build failed." }
    } finally { Pop-Location }
    Write-Okay "frontend built -> frontend\dist"
  }

  Start-Backend
  if ($Mode -eq "dev") { Start-Frontend }

  if ($Mode -eq "dev") {
Write-Host @"
------------------------------------------------------------
  Frontend :  http://127.0.0.1:$FrontendPort
  API docs :  http://127.0.0.1:$BackendPort/docs
  Login    :  admin / admin123   (change it ASAP)

  logs     :  .\xbow.bat logs -f
  status   :  .\xbow.bat status
  stop     :  .\xbow.bat stop
------------------------------------------------------------
"@
  } else {
Write-Host @"
------------------------------------------------------------
  Backend  :  http://0.0.0.0:$BackendPort
  API docs :  http://0.0.0.0:$BackendPort/docs
  Static   :  $FrontendDir\dist   (serve via nginx / IIS, see notes)
  Login    :  admin / admin123   (change it ASAP!)

  logs     :  .\xbow.bat logs backend -f
  status   :  .\xbow.bat status
  stop     :  .\xbow.bat stop
  Tip: set XBOW_CYBER_RANGE_CORS_ORIGINS in backend\.env accordingly.
------------------------------------------------------------
"@
  }
}

function Invoke-Restart {
  Invoke-Stop
  Start-Sleep -Seconds 1
  Invoke-Start
}

function Invoke-Install {
  Resolve-Python
  Check-Docker
  Setup-Backend
  Check-Node
  Setup-Frontend
  Write-Okay "dependencies installed. Run '.\xbow.bat start' (dev) or '.\xbow.bat start --prod'."
}

# ---------- main ----------
switch ($Command) {
  "start"   { Invoke-Start }
  "stop"    { Invoke-Stop }
  "restart" { Invoke-Restart }
  "status"  { Invoke-Status }
  "logs"    { Invoke-Logs }
  "install" { Invoke-Install }
}
