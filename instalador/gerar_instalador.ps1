# Gera o instalador do Canais Abertos:
#   1) PyInstaller empacota o programa + Python + o motor do VLC (pasta vlc/)
#   2) NSIS monta o instalador CanaisAbertos-Setup-<versao>.exe nesta pasta
# Uso: powershell -ExecutionPolicy Bypass -File gerar_instalador.ps1
$ErrorActionPreference = 'Stop'
$aqui = $PSScriptRoot
$prog = Join-Path (Split-Path $aqui -Parent) 'canais_abertos.py'
$vlc = 'C:\Program Files\VideoLAN\VLC'
$icone = Join-Path $aqui 'canais_abertos.ico'
$makensis = Get-ChildItem "$env:LOCALAPPDATA\electron-builder\Cache" -Recurse -Filter makensis.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.DirectoryName -notmatch '\\Bin$' } | Select-Object -First 1 -ExpandProperty FullName
if (-not (Test-Path "$vlc\libvlc.dll")) { throw "VLC 64 bits nao encontrado em $vlc" }
if (-not $makensis) { throw "makensis.exe (NSIS) nao encontrado" }

Set-Location $aqui
python -m PyInstaller --noconfirm --clean --windowed --name 'Canais Abertos' --icon $icone `
    --add-data "$icone;." `
    --add-binary "$vlc\libvlc.dll;vlc" --add-binary "$vlc\libvlccore.dll;vlc" `
    --add-data "$vlc\plugins;vlc\plugins" `
    --workpath (Join-Path $aqui 'build') --distpath (Join-Path $aqui 'dist') --specpath (Join-Path $aqui 'build') `
    $prog
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou" }
& $makensis /V2 (Join-Path $aqui 'canais_abertos.nsi')
if ($LASTEXITCODE -ne 0) { throw "NSIS falhou" }
Get-ChildItem $aqui -Filter 'CanaisAbertos-Setup-*.exe' | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,1)}}
