# Build MIDI-Studio for Windows 10/11 (64-bit) with PyInstaller.  v22ze-122
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Work = Join-Path $Root "build\windows"
$Dist = Join-Path $Root "dist\windows"
Set-Location $Root

foreach ($f in "main.py","gui.py","midi_io.py","audio_backend.py","app_resources.py") {
    if (-not (Test-Path (Join-Path $Root $f))) { throw "Missing $f - run this from the repo." }
}

# --- find Python 3.12 (64-bit) -------------------------------------------------
$py = $null
try { & py -3.12 -c "import sys; assert sys.maxsize > 2**32" 2>$null; if ($LASTEXITCODE -eq 0) { $py = @("py","-3.12") } } catch {}
if (-not $py) {
    try { & python -c "import sys; assert sys.version_info[:2]==(3,12) and sys.maxsize > 2**32" 2>$null; if ($LASTEXITCODE -eq 0) { $py = @("python") } } catch {}
}
if (-not $py) {
    throw "Python 3.12 (64-bit) not found. Install it from python.org (tick 'Add python.exe to PATH'), then run this again."
}
Write-Host "Using:" ($py -join " ")

# --- venv + requirements -------------------------------------------------------
$venv = Join-Path $Work "venv"
$vpy  = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    New-Item -ItemType Directory -Force -Path $Work | Out-Null
    $pyArgs = @()
    if ($py.Length -gt 1) { $pyArgs = $py[1..($py.Length-1)] }
    & $py[0] @pyArgs -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}
& $vpy -m pip install --upgrade pip
& $vpy -m pip install mido python-rtmidi pyfluidsynth python-ly pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# --- compile check + build -----------------------------------------------------
& $vpy -m py_compile (Join-Path $Root "main.py")
if ($LASTEXITCODE -ne 0) { throw "main.py does not compile" }

if (Test-Path (Join-Path $Dist "MIDI-Studio")) { Remove-Item -Recurse -Force (Join-Path $Dist "MIDI-Studio") }
& $vpy -m PyInstaller --noconfirm --clean `
    --distpath $Dist --workpath (Join-Path $Work "pyi") `
    (Join-Path $Root "packaging\windows\midi-studio.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$exe = Join-Path $Dist "MIDI-Studio\MIDI-Studio.exe"
if (-not (Test-Path $exe)) { throw "Build finished but $exe is missing" }
$mb = [math]::Round(((Get-ChildItem (Join-Path $Dist "MIDI-Studio") -Recurse | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Host ""
Write-Host "BUILT: $exe  (folder size $mb MB)"
Write-Host "Next: packaging\windows\smoke_test.cmd"
