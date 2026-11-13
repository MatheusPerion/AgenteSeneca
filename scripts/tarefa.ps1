# Sêneca: cria uma tarefa, uma sessão do Claude em segundo plano que abre sozinha no app do Claude.
# Uso: scripts/tarefa.ps1 -Tarefa "descrição completa" [-Pasta "D:\Workspace\Projeto"] [-Nome "nome-curto"]
# Relatório em tarefas\. A bandeja abre a sessão no app e avisa por voz quando termina.
param(
    [Parameter(Mandatory = $true)][string]$Tarefa,
    [string]$Pasta,
    [string]$Nome,
    [string]$Base,       # uso interno
    [string]$Sessao,     # uso interno
    [switch]$Executar    # uso interno
)
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$raiz = Split-Path -Parent $PSScriptRoot

if (-not $Executar) {
    if (-not $Pasta) { $Pasta = $raiz }
    if (-not (Test-Path $Pasta)) { "ERRO: pasta não existe: $Pasta"; exit 1 }
    if (-not $Nome) { $Nome = ($Tarefa -split '\s+' | Select-Object -First 5) -join '-' }
    $Nome = ($Nome.ToLower() -replace '[^a-z0-9\-]', '' -replace '-+', '-').Trim('-')
    if (-not $Nome) { $Nome = 'tarefa' }
    $dir = Join-Path $raiz 'tarefas'
    New-Item -ItemType Directory -Force $dir | Out-Null
    $base = Join-Path $dir "$(Get-Date -Format 'yyyy-MM-dd_HHmm')-$Nome"
    $sessao = [guid]::NewGuid().ToString()
    Set-Content -Path "$base.tarefa.txt" -Value $Tarefa -Encoding UTF8
@"
# Tarefa: $Nome

- **Status:** em andamento
- **Início:** $(Get-Date -Format 'yyyy-MM-dd HH:mm')
- **Pasta:** $Pasta
- **Sessão Claude:** $sessao

## Pedido
$Tarefa

## Resultado
"@ | Set-Content -Path "$base.md" -Encoding UTF8
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-Executar', '-Tarefa', 'x',
        '-Base', "`"$base`"", '-Pasta', "`"$Pasta`"", '-Sessao', $sessao
    )
    "Tarefa criada: $base.md"
    exit 0
}

# ---------- execução em segundo plano
Set-Content -Path "$Base.pid" -Value $PID -Encoding ASCII     # o painel usa no botão Parar
$tarefa = Get-Content -Raw -Encoding UTF8 "$Base.tarefa.txt"
$prompt = @"
$tarefa

Regras desta tarefa:
- Você trabalha sozinho, em segundo plano; ninguém vai responder perguntas. Decida com bom senso e anote as suposições.
- Só faça git commit, push ou pull se este pedido disser explicitamente. Nunca use push --force e não apague arquivos.
- No final, responda em português: o que foi feito, arquivos alterados, problemas encontrados e próximos passos sugeridos.
"@
$notion = 'search', 'fetch', 'query-data-sources', 'query-multiple-data-sources', 'get-comments', 'get-users' | ForEach-Object { "mcp__claude_ai_Notion__notion-$_" }
$git = 'status', 'diff', 'log', 'branch', 'show', 'add', 'commit', 'push', 'pull'
$ferramentas = @('Read', 'Edit', 'Write', 'Glob', 'Grep', 'WebSearch', 'WebFetch', 'Task', 'TodoWrite') + $notion +
    ($git | ForEach-Object { "Bash(git ${_}:*)"; "PowerShell(git ${_}:*)" }) +
    @('Bash(npm test:*)', 'Bash(npm run:*)', 'Bash(dotnet build:*)', 'Bash(dotnet test:*)', 'Bash(python -m pytest:*)')
$proibidas = 'Bash(git push *--force*)', 'Bash(git push -f*)', 'Bash(git push * -f*)', 'Bash(rm:*)', 'Bash(del:*)', 'Bash(Remove-Item:*)',
    'PowerShell(git push *--force*)', 'PowerShell(git push -f*)', 'PowerShell(git push * -f*)', 'PowerShell(rm:*)', 'PowerShell(del:*)', 'PowerShell(Remove-Item:*)'
$titulo = 'Sêneca · ' + (((Split-Path -Leaf $Base) -replace '^\d{4}-\d{2}-\d{2}_\d{4}-', '') -replace '-', ' ')
$claude = Join-Path $raiz 'app\node_modules\@anthropic-ai\claude-agent-sdk-win32-x64\claude.exe'
$log = "$Base.log.jsonl"                                       # o painel lê ao vivo
$utf8 = New-Object System.Text.UTF8Encoding($false)
$script:final = $null; $script:erro = $false; $script:outras = @()
Push-Location $Pasta
try {
    $prompt | & $claude -p --session-id $Sessao --name $titulo --output-format stream-json --verbose --permission-mode acceptEdits `
        --allowedTools ($ferramentas -join ',') --disallowedTools ($proibidas -join ',') 2>&1 | ForEach-Object {
        $linha = "$_"
        if (-not $linha.Trim()) { return }
        if ($linha.TrimStart().StartsWith('{')) {
            [IO.File]::AppendAllText($log, $linha + "`n", $utf8)
            try { $ev = $linha | ConvertFrom-Json; if ($ev.type -eq 'result') { $script:final = $ev.result; $script:erro = [bool]$ev.is_error } } catch {}
        } else {
            $script:outras += $linha
            [IO.File]::AppendAllText($log, (@{ type = 'stderr'; text = $linha } | ConvertTo-Json -Compress) + "`n", $utf8)
        }
    }
    $ok = ($LASTEXITCODE -eq 0) -and -not $script:erro
    $saida = if ($script:final) { $script:final } else { $script:outras -join "`n" }
} catch { $saida = "Erro ao executar o Claude: $_"; $ok = $false } finally { Pop-Location }

Add-Content -Path "$Base.md" -Value $saida -Encoding UTF8
$status = if ($ok) { 'concluída' } else { 'falhou' }
$md = (Get-Content -Raw -Encoding UTF8 "$Base.md") -replace '\*\*Status:\*\* em andamento', "**Status:** $status ($(Get-Date -Format 'HH:mm'))"
Set-Content -Path "$Base.md" -Value $md -Encoding UTF8
[IO.File]::Delete("$Base.tarefa.txt"); [IO.File]::Delete("$Base.pid")
