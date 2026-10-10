# Fetch the native payload for the Windows build.  v22ze-123
#   libfluidsynth + its DLLs  -> packaging\windows\payload\lib
#   MuseScore_General.sf3     -> packaging\windows\payload\sound
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # much faster downloads in Windows PowerShell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Lib  = Join-Path $Root "packaging\windows\payload\lib"
$Snd  = Join-Path $Root "packaging\windows\payload\sound"
$FsVersion = "2.6.0"
$FsZip = "fluidsynth-v$FsVersion-win10-x64-cpp11.zip"
$FsUrl = "https://github.com/FluidSynth/fluidsynth/releases/download/v$FsVersion/$FsZip"
$SfBase = "https://ftp.osuosl.org/pub/musescore/soundfont/MuseScore_General"

# v22ze-158: a short network/DNS hiccup on the build machine must not fail the whole build.
function Get-WithRetry([string]$Uri, [string]$OutFile) {
    for ($i = 1; $i -le 6; $i++) {
        try {
            Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing
            return
        } catch {
            if ($i -eq 6) { throw }
            $wait = 10 * $i
            Write-Host "Download failed ($($_.Exception.Message)); retry $i of 5 in $wait s"
            Start-Sleep -Seconds $wait
        }
    }
}

$tmp = Join-Path $env:TEMP "midistudio-fetch"
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
New-Item -ItemType Directory -Force -Path $tmp, $Lib, $Snd | Out-Null

# ---- FluidSynth ---------------------------------------------------------------
Write-Host "Downloading $FsZip"
$zip = Join-Path $tmp $FsZip
Get-WithRetry $FsUrl $zip
Write-Host ("sha256 " + (Get-FileHash $zip -Algorithm SHA256).Hash + "  " + $FsZip)
Expand-Archive -Path $zip -DestinationPath (Join-Path $tmp "fs") -Force

$dlls = Get-ChildItem (Join-Path $tmp "fs") -Recurse -Filter *.dll
if (-not ($dlls | Where-Object { $_.Name -like "libfluidsynth*.dll" })) {
    Write-Host "Contents of the zip:"
    Get-ChildItem (Join-Path $tmp "fs") -Recurse | ForEach-Object { Write-Host ("  " + $_.FullName.Substring($tmp.Length)) }
    throw "No libfluidsynth*.dll found in $FsZip"
}
Get-ChildItem $Lib -Filter *.dll -ErrorAction SilentlyContinue | Remove-Item -Force
foreach ($d in $dlls) { Copy-Item $d.FullName (Join-Path $Lib $d.Name) -Force }

# Microsoft's C++ runtime DLLs that FluidSynth may need and that a clean PC may
# lack (app-local deployment of these files is permitted).  Only copies what is
# missing from the bundle and present on this machine.
foreach ($n in "msvcp140.dll","msvcp140_1.dll","vcruntime140.dll","vcruntime140_1.dll","concrt140.dll") {
    $src = Join-Path $env:WINDIR ("System32\" + $n)
    if ((Test-Path $src) -and -not (Test-Path (Join-Path $Lib $n))) {
        Copy-Item $src (Join-Path $Lib $n) -Force
        Write-Host "  + runtime $n"
    }
}

$lic = Join-Path $Lib "LICENSES\fluidsynth"
New-Item -ItemType Directory -Force -Path $lic | Out-Null
Get-ChildItem (Join-Path $tmp "fs") -Recurse -File |
    Where-Object { $_.Name -match '^(LICENSE|COPYING)' } |
    ForEach-Object { Copy-Item $_.FullName $lic -Force }
Set-Content -Path (Join-Path $Lib "LICENSES\README.txt") -Encoding ASCII -Value @(
    "FluidSynth $FsVersion (LGPL-2.1), official Windows build: $FsUrl",
    "Source: https://github.com/FluidSynth/fluidsynth (tag v$FsVersion).",
    "The DLLs are dynamically linked and can be replaced by the user.",
    "Other DLLs in this folder are FluidSynth's dependencies, shipped in the same official zip,",
    "and Microsoft Visual C++ runtime files (app-local redistribution)."
)
Write-Host "lib\ now holds:"
Get-ChildItem $Lib -Filter *.dll | ForEach-Object { Write-Host ("  " + $_.Name + "  " + [math]::Round($_.Length/1KB) + " KB") }

# ---- Soundfont ----------------------------------------------------------------
foreach ($f in "MuseScore_General.sf3","MuseScore_General_License.md","MuseScore_General_Readme.md","MuseScore_General_Sample_Sources.csv") {
    Write-Host "Downloading $f"
    Get-WithRetry "$SfBase/$f" (Join-Path $Snd $f)
}
$sf = Join-Path $Snd "MuseScore_General.sf3"
$head = [System.IO.File]::ReadAllBytes($sf)[0..11]
if ([System.Text.Encoding]::ASCII.GetString($head[8..11]) -ne "sfbk") { throw "MuseScore_General.sf3 is not a SoundFont file" }
if ((Get-Item $sf).Length -lt 20000000) { throw "MuseScore_General.sf3 is too small" }
Write-Host ("sha256 " + (Get-FileHash $sf -Algorithm SHA256).Hash + "  MuseScore_General.sf3 (" + (Get-Item $sf).Length + " bytes)")
Write-Host "Payload ready."
