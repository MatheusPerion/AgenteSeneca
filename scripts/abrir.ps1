# Abre um aplicativo do menu Iniciar (ou um site) pelo nome.
# Uso:
#   .\abrir.ps1 Spotify            .\abrir.ps1 "visual studio code"        .\abrir.ps1 https://youtube.com
#   .\abrir.ps1 -Listar            (mostra os apps disponíveis)
# Por segurança, só abre apps do menu Iniciar e sites http(s); não executa caminhos ou comandos arbitrários.
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)][string[]]$Nome,
    [switch]$Listar
)
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$alvo = ($Nome -join ' ').Trim().Trim('"', "'")

function Normalizar([string]$s) {
    $d = $s.ToLowerInvariant().Normalize([Text.NormalizationForm]::FormD)
    (-join ($d.ToCharArray() | Where-Object { [Globalization.CharUnicodeInfo]::GetUnicodeCategory($_) -ne 'NonSpacingMark' })) -replace '[^a-z0-9 ]', ' ' -replace '\s+', ' '
}

# apelidos falados -> nome no menu Iniciar
$apelidos = @{
    'navegador' = 'Brave'; 'internet' = 'Brave'; 'browser' = 'Brave'
    'vscode' = 'Visual Studio Code'; 'vs code' = 'Visual Studio Code'; 'code' = 'Visual Studio Code'
    'explorador' = 'Explorador de Arquivos'; 'arquivos' = 'Explorador de Arquivos'; 'pastas' = 'Explorador de Arquivos'
    'lol' = 'League of Legends'; 'league' = 'League of Legends'; 'riot' = 'Cliente Riot'; 'tft' = 'League of Legends'
    'calculadora' = 'Calculadora'; 'notas' = 'Obsidian'; 'memoria' = 'Obsidian'
}

# site: abre direto (listar os apps do menu Iniciar demora)
if (-not $Listar -and $alvo -match '^https?://') { Start-Process $alvo; "Abri $alvo no navegador."; exit 0 }

$apps = Get-StartApps | Where-Object { $_.Name -notmatch 'uninstall|desinstalar|support center|leia-me|readme' }
if ($Listar -or -not $alvo) { ($apps | Sort-Object Name | ForEach-Object Name) -join '; '; exit 0 }

$n = Normalizar $alvo
if ($apelidos.ContainsKey($n)) { $n = Normalizar $apelidos[$n] }
$escolhido = $apps | Where-Object { (Normalizar $_.Name) -eq $n } | Select-Object -First 1
if (-not $escolhido) { $escolhido = $apps | Where-Object { (Normalizar $_.Name).StartsWith($n) } | Sort-Object { $_.Name.Length } | Select-Object -First 1 }
if (-not $escolhido) { $escolhido = $apps | Where-Object { (Normalizar $_.Name).Contains($n) } | Sort-Object { $_.Name.Length } | Select-Object -First 1 }
if (-not $escolhido) {
    $palavras = $n.Split(' ') | Where-Object { $_.Length -ge 3 }
    $escolhido = $apps | Where-Object { $nn = Normalizar $_.Name; ($palavras | Where-Object { $nn.Contains($_) }).Count -eq $palavras.Count } | Select-Object -First 1
}
if (-not $escolhido) {
    $parecidos = ($apps | Where-Object { (Normalizar $_.Name).Contains($n.Substring(0, [Math]::Min(3, $n.Length))) } | Select-Object -First 5 | ForEach-Object Name) -join ', '
    "Não achei o app '$alvo'." + $(if ($parecidos) { " Parecidos: $parecidos." } else { ' Use -Listar para ver todos.' })
    exit 1
}

$id = $escolhido.AppID
try {
    if ($id -match '^https?://') { Start-Process $id }
    elseif ($id -match '^[A-Za-z]:\\' -and (Test-Path $id)) { Start-Process $id }
    else { Start-Process "shell:AppsFolder\$id" }
    "Abri $($escolhido.Name)."
} catch {
    "Não consegui abrir $($escolhido.Name): $($_.Exception.Message)"
    exit 1
}
