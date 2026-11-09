$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project
$python = Join-Path $project '.venv\Scripts\python.exe'
$versionLine = Select-String -LiteralPath 'src\medialink\__init__.py' -Pattern '^__version__ = "(\d+\.\d+\.\d+)"$'
$version = $versionLine.Matches[0].Groups[1].Value
$appName = 'MediaLinkDownloader'
foreach ($file in @($python,'runtime\ffmpeg.exe','runtime\ffprobe.exe','runtime\LICENSE')) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing file: $file" }
}
foreach ($dir in @('build','dist','.cache')) {
    if ((Test-Path -LiteralPath $dir) -and (Get-Item -LiteralPath $dir -Force).Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)) {
        throw "Build directory is a reparse point: $dir"
    }
}
$buildId = [Guid]::NewGuid().ToString('N').Substring(0,12)
$stage = Join-Path $project "build\$buildId"
$env:TMP = Join-Path $stage 'tmp'
$env:TEMP = $env:TMP
$env:PYINSTALLER_CONFIG_DIR = Join-Path $project '.cache\pyinstaller'
New-Item -ItemType Directory -Force -Path $stage,$env:TMP,'dist' | Out-Null
$env:QT_QPA_PLATFORM = 'offscreen'
$icon = Join-Path $stage 'medialink.ico'
$basePython = & $python -c 'import sys; print(sys.base_prefix)'
if ($LASTEXITCODE -ne 0) { throw 'Unable to locate the build interpreter.' }
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$basePython"
& $python -X utf8 scripts\build_icon.py $icon
if ($LASTEXITCODE -ne 0) { throw 'Icon build failed.' }
$buildArgs = @(
    '--onedir', '--windowed', '--noupx', '--name', $appName, '--icon', $icon,
    '--distpath', $stage, '--workpath', (Join-Path $stage 'work'), '--specpath', $stage,
    '--paths', (Join-Path $project 'src'),
    '--copy-metadata', 'PySide6-Essentials', '--copy-metadata', 'qrcode',
    '--copy-metadata', 'yt-dlp', '--copy-metadata', 'requests',
    '--copy-metadata', 'websocket-client',
    (Join-Path $project 'src\medialink_app.py')
)
& $python -X utf8 -m PyInstaller @buildArgs
if ($LASTEXITCODE -ne 0) { throw 'Application build failed.' }

$bundle = Join-Path $stage $appName
$bundleRuntime = Join-Path $bundle 'runtime'
New-Item -ItemType Directory -Path $bundleRuntime | Out-Null
foreach ($file in @('ffmpeg.exe','ffprobe.exe','LICENSE','README.txt')) {
    if (Test-Path -LiteralPath "runtime\$file" -PathType Leaf) {
        Copy-Item -LiteralPath "runtime\$file" -Destination $bundleRuntime
    }
}
Copy-Item -LiteralPath 'README.md','THIRD_PARTY.md' -Destination $bundle
$name = "$appName-v$version"
$dist = Join-Path $project 'dist'
if ((Test-Path -LiteralPath (Join-Path $dist $name)) -or (Test-Path -LiteralPath (Join-Path $dist "$name-win-x64.zip"))) {
    $name += "-$buildId"
}
$destination = Join-Path $dist $name
$zip = Join-Path $dist "$name-win-x64.zip"
Move-Item -LiteralPath $bundle -Destination $destination
Compress-Archive -LiteralPath $destination -DestinationPath $zip -CompressionLevel Fastest
Write-Output (Join-Path $destination "$appName.exe")
Write-Output $zip
