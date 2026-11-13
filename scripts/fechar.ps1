# Sêneca: fecha um aplicativo aberto, pelo nome.
# Uso: scripts/fechar.ps1 Discord | scripts/fechar.ps1 tft | scripts/fechar.ps1 Discord -Forcar | scripts/fechar.ps1 -Listar
# Primeiro pede para o app fechar normalmente (ele pode perguntar se quer salvar). -Forcar encerra na marra e perde o que não foi salvo.
# Por segurança, nunca encerra processos do Windows, o antivírus, o Claude ou o próprio Sêneca.
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)][string[]]$Nome,
    [switch]$Forcar,
    [switch]$Listar
)
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Normalizar([string]$s) {
    $d = $s.ToLowerInvariant().Normalize([Text.NormalizationForm]::FormD)
    (-join ($d.ToCharArray() | Where-Object { [Globalization.CharUnicodeInfo]::GetUnicodeCategory($_) -ne 'NonSpacingMark' })) -replace '[^a-z0-9]', ''
}

$protegidos = @(
    'system', 'idle', 'registry', 'memorycompression', 'csrss', 'smss', 'wininit', 'winlogon', 'services', 'lsass', 'lsaiso',
    'svchost', 'dwm', 'fontdrvhost', 'explorer', 'sihost', 'ctfmon', 'taskhostw', 'runtimebroker', 'applicationframehost',
    'searchhost', 'startmenuexperiencehost', 'shellexperiencehost', 'textinputhost', 'spoolsv', 'audiodg', 'conhost',
    'securityhealthservice', 'securityhealthsystray', 'msmpeng', 'nissrv', 'mpdefendercoreservice', 'wuauclt', 'taskmgr',
    'claude', 'python', 'pythonw', 'node', 'powershell', 'pwsh', 'cmd', 'msedgewebview2', 'bash'
)
function Protegido($p) { ($protegidos -contains (Normalizar $p.ProcessName)) -or ($p.Id -eq $PID) }

# apelidos falados -> nome do processo
$apelidos = @{
    'navegador' = @('brave'); 'internet' = @('brave'); 'browser' = @('brave'); 'edge' = @('msedge')
    'vscode' = @('Code'); 'visualstudiocode' = @('Code'); 'code' = @('Code')
    'lol' = @('LeagueClientUx', 'LeagueClient', 'League of Legends'); 'league' = @('LeagueClientUx', 'LeagueClient', 'League of Legends')
    'leagueoflegends' = @('LeagueClientUx', 'LeagueClient', 'League of Legends')
    'tft' = @('TFTClient-Win64-Shipping'); 'teamfighttactics' = @('TFTClient-Win64-Shipping')
    'riot' = @('RiotClientUx', 'Riot Client'); 'calculadora' = @('CalculatorApp'); 'notas' = @('Obsidian')
}

$todos = Get-Process
if ($Listar) {
    ($todos | Where-Object { $_.MainWindowHandle -ne 0 -and -not (Protegido $_) } | Sort-Object ProcessName -Unique |
        ForEach-Object { "$($_.ProcessName) ($($_.MainWindowTitle))" }) -join '; '
    exit 0
}

$alvo = ($Nome -join ' ').Trim().Trim('"', "'")
$n = Normalizar $alvo
if (-not $n) { 'Diga qual aplicativo fechar.'; exit 1 }
if ($protegidos -contains $n) { "Por segurança, não fecho $alvo."; exit 4 }

$nomes = if ($apelidos.ContainsKey($n)) { $apelidos[$n] | ForEach-Object { Normalizar $_ } } else { @($n) }
$livres = $todos | Where-Object { -not (Protegido $_) }
$achados = @($livres | Where-Object { $nomes -contains (Normalizar $_.ProcessName) })
if (-not $achados.Count -and $n.Length -ge 3) {
    # não achou pelo nome exato: procura em quem tem janela, pelo nome do processo ou o título
    $parecidos = @($livres | Where-Object { $_.MainWindowHandle -ne 0 -and ((Normalizar $_.ProcessName).Contains($n) -or (Normalizar $_.MainWindowTitle).Contains($n)) })
    $distintos = @($parecidos | Sort-Object ProcessName -Unique)
    if ($distintos.Count -gt 1) { "Achei mais de um: $(($distintos | ForEach-Object ProcessName) -join ', '). Diga qual."; exit 2 }
    if ($distintos.Count -eq 1) { $achados = @($livres | Where-Object { $_.ProcessName -eq $distintos[0].ProcessName }) }
}
if (-not $achados.Count) { "$alvo não está aberto."; exit 1 }

$rotulo = $achados[0].ProcessName
$janelas = @($achados | Where-Object { $_.MainWindowHandle -ne 0 })
if ($Forcar -or -not $janelas.Count) {            # sem janela não há o que perguntar ao usuário
    $achados | Stop-Process -Force -ErrorAction SilentlyContinue
    "Encerrei $rotulo."
    exit 0
}
$janelas | ForEach-Object { [void]$_.CloseMainWindow() }
$limite = (Get-Date).AddSeconds(5)
do {
    Start-Sleep -Milliseconds 250
    $abertas = @($janelas | Where-Object { -not $_.HasExited })
} while ($abertas.Count -and (Get-Date) -lt $limite)
if ($abertas.Count) { "$rotulo não fechou; pode estar perguntando se quer salvar. Para encerrar na marra, peça para forçar."; exit 3 }
"Fechei $rotulo."
