# SHARP Splat para Nuke - desinstalador. Quita la carpeta del plugin y su bloque del menu.py.
param([string]$NukeDir = (Join-Path $env:USERPROFILE '.nuke'))
$ErrorActionPreference = 'Stop'
$Latin1 = [Text.Encoding]::GetEncoding(28591)
$dst = Join-Path $NukeDir 'sharp_splat'
if (Test-Path $dst) { Remove-Item -Recurse -Force $dst; Write-Host "Borrado $dst" }
$menu = Join-Path $NukeDir 'menu.py'
if (Test-Path $menu) {
    $text = [IO.File]::ReadAllText($menu, $Latin1)
    $new = [regex]::Replace($text, '(?s)# >>> SHARP Splat >>>.*?# <<< SHARP Splat <<<\r?\n?', '')
    if ($new -ne $text) { [IO.File]::WriteAllText($menu, $new, $Latin1); Write-Host 'Menu quitado de menu.py' }
}
Write-Host 'SHARP Splat desinstalado.' -ForegroundColor Green
