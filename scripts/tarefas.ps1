# Sêneca: lista as tarefas recentes do Claude com o status de cada uma.
param([int]$Quantas = 8)
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$dir = Join-Path (Split-Path -Parent $PSScriptRoot) 'tarefas'
$lista = Get-ChildItem $dir -Filter *.md -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First $Quantas
if (-not $lista) { 'Nenhuma tarefa ainda.'; exit 0 }
$lista | ForEach-Object {
    $t = Get-Content -Raw -Encoding UTF8 $_.FullName
    $s = if ($t -match '\*\*Status:\*\* ([^\r\n]+)') { $Matches[1] } else { '?' }
    "=== $($_.BaseName) | $s ===`n" + $t.Substring(0, [Math]::Min(1500, $t.Length))
}
