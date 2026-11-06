# SHARP Splat para Nuke - instalador (Windows PowerShell 5.1). Sin acentos a proposito: PS 5.1 lee .ps1 sin BOM como ANSI.
# Uso normal: doble clic en instalar.bat. Opcion: -NukeDir <carpeta .nuke>
param([string]$NukeDir = (Join-Path $env:USERPROFILE '.nuke'))
$ErrorActionPreference = 'Stop'

$Src = Join-Path (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)) 'nuke\sharp_splat'
$Latin1 = [Text.Encoding]::GetEncoding(28591)  # bytes <-> chars 1 a 1: no toca los acentos del menu.py
$warn = @()

function Step($m) { Write-Host ''; Write-Host "==> $m" -ForegroundColor Cyan }

Step "Copiando el plugin a $NukeDir\sharp_splat"
if (-not (Test-Path $Src)) { throw "No encuentro el plugin en $Src" }
New-Item -ItemType Directory -Force $NukeDir | Out-Null
$dst = Join-Path $NukeDir 'sharp_splat'
if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
Copy-Item $Src $dst -Recurse
Get-ChildItem $dst -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force

Step 'Agregando el menu (Nodes > 3D > SHARP Splat)'
$menu = Join-Path $NukeDir 'menu.py'
$block = "# >>> SHARP Splat >>>`r`nimport nuke`r`ntry:`r`n    import sharp_splat`r`n    sharp_splat.register()`r`n" +
         "except Exception as e:`r`n    nuke.tprint('SHARP Splat: no se pudo cargar: %s' % e)`r`n# <<< SHARP Splat <<<`r`n"
$text = ''
if (Test-Path $menu) {
    if (-not (Test-Path "$menu.bak_sharp_splat")) { Copy-Item $menu "$menu.bak_sharp_splat" }
    $text = [IO.File]::ReadAllText($menu, $Latin1)
}
$text = [regex]::Replace($text, '(?s)# >>> SHARP Splat >>>.*?# <<< SHARP Splat <<<\r?\n?', '')
if ($text.Length -gt 0 -and -not $text.EndsWith("`n")) { $text += "`r`n" }
[IO.File]::WriteAllText($menu, $text + $block, $Latin1)
Write-Host "Listo (copia de seguridad: menu.py.bak_sharp_splat)"

Step 'Revisando lo que necesita'
if (-not (Get-ChildItem 'C:\Program Files' -Directory -Filter 'Nuke17*' -ErrorAction SilentlyContinue)) {
    $warn += 'No encontre Nuke 17 en C:\Program Files: SHARP Splat necesita Nuke 17 o mas nuevo (SplatRender).'
}
# los mismos lugares donde lo busca el plugin (comfy.py): Comfy Desktop usa 8000, ComfyUI portable 8188
$urls = if ($env:SHARP_SPLAT_COMFYUI_URL) { @($env:SHARP_SPLAT_COMFYUI_URL) } else { @('http://127.0.0.1:8000', 'http://127.0.0.1:8188') }
$url = $urls[0]
foreach ($u in $urls) {
    try { Invoke-WebRequest -UseBasicParsing -Uri "$($u.TrimEnd('/'))/system_stats" -TimeoutSec 2 | Out-Null; $url = $u; break } catch {}
}
$need = @{ 'SharpHDR_Predict' = 'ComfyUI-SHARP-HDR'; 'LoadSharpModel' = 'ComfyUI-Sharp'; 'LoadEXR' = 'ComfyUI-HQ-Image-Save' }
try {
    foreach ($node in $need.Keys) {
        # de a un nodo: PS 5.1 no logra convertir el /object_info completo
        $raw = (Invoke-WebRequest -UseBasicParsing -Uri "$($url.TrimEnd('/'))/object_info/$node" -TimeoutSec 10).Content
        if ($raw -match "`"$node`"") { Write-Host "ComfyUI: $node OK" }
        else { $warn += "ComfyUI no tiene el nodo ${node}: instala $($need[$node]) con ComfyUI Manager y reinicia ComfyUI." }
    }
} catch {
    $warn += "ComfyUI no responde en $url, asi que no pude revisar sus nodos. Necesita ComfyUI-Sharp, ComfyUI-SHARP-HDR y ComfyUI-HQ-Image-Save (si falta alguno, Nuke te lo dice al Generar)."
}

Write-Host ''
if ($warn.Count) { $warn | ForEach-Object { Write-Warning $_ } }
Write-Host 'SHARP Splat instalado. Abre Nuke 17 y busca Nodes > 3D > SHARP Splat.' -ForegroundColor Green
