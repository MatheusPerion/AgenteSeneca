# Sêneca: instala tudo (Python, Node, vozes) e pergunta seus dados — rode uma vez, depois do git clone.
# Uso: scripts/instalar.ps1   (ou dê duplo-clique em Instalar.bat, na pasta de cima)
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
$ErroFatal = $false

function Titulo($t) { "`n=== $t ===" }
function Tem($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

Titulo "Verificando Python e Node"
if (-not (Tem python)) {
    "Python não encontrado. Instale o Python 3.12+ (https://python.org/downloads ou 'winget install Python.Python.3.12') e rode este script de novo."
    $ErroFatal = $true
}
if (-not (Tem node)) {
    "Node.js não encontrado. Instale o Node 18+ (https://nodejs.org ou 'winget install OpenJS.NodeJS.LTS') e rode este script de novo."
    $ErroFatal = $true
}
if ($ErroFatal) { "`nInstale o que falta acima e rode scripts/instalar.ps1 de novo."; exit 1 }
"Python e Node encontrados."

Titulo "Ambiente Python (.venv)"
if (Tem uv) {
    uv venv
    uv pip install -r requirements.txt
} else {
    python -m venv .venv
    & .venv\Scripts\python.exe -m pip install --upgrade pip
    & .venv\Scripts\pip.exe install -r requirements.txt
}

Titulo "Dependências do cérebro (Node)"
Push-Location (Join-Path $raiz "app")
npm install
Pop-Location

Titulo "Seus dados (ficam só nesta máquina; não vão pro git)"
if (-not (Test-Path "memoria\perfil.md")) {
    $nome = Read-Host "Seu nome"
    $apelido = Read-Host "Como prefere ser chamado (Enter para usar o nome mesmo)"
    if (-not $apelido) { $apelido = $nome }
    $cidade = Read-Host "Sua cidade (para o clima, sem acento; Enter para pular)"
    $fuso = Read-Host "Fuso horário (Enter para America/Sao_Paulo)"
    if (-not $fuso) { $fuso = "America/Sao_Paulo" }
    $padraoWorkspace = Split-Path -Parent $raiz
    $workspace = Read-Host "Pasta onde ficam seus outros projetos (Enter para usar $padraoWorkspace)"
    if (-not $workspace) { $workspace = $padraoWorkspace }

    @"
# Perfil — $nome

- **Nome:** $nome
- **Como prefere ser tratado:** $apelido
- **Idioma:** português (BR)
- **Cidade:** $cidade
- **Fuso horário:** $fuso

## Preferências
-

## Rotina
- Horário do briefing matinal: 08:00 (ajustável)

## Ferramentas conectadas
- **Notion:** se conectar, anote aqui o nome do banco de tarefas e configure `notion_banco` em `app/config.json`.
"@ | Set-Content -Path "memoria\perfil.md" -Encoding UTF8

    foreach ($f in "objetivos", "tarefas", "projetos", "respostas-prontas") {
        if (-not (Test-Path "memoria\$f.md")) { Copy-Item "memoria\$f.exemplo.md" "memoria\$f.md" }
    }

    # app/config.json: a bandeja cria os padrões sozinha na 1ª vez; aqui só gravamos o que você respondeu.
    $cfg = [ordered]@{}
    if (Test-Path "app\config.json") {
        (Get-Content "app\config.json" -Raw | ConvertFrom-Json).psobject.Properties | ForEach-Object { $cfg[$_.Name] = $_.Value }
    }
    $cfg["nome"] = $apelido
    $cfg["cidade_clima"] = $cidade
    $cfg["workspace"] = $workspace
    $cfg | ConvertTo-Json -Depth 5 | Set-Content -Path "app\config.json" -Encoding UTF8

    # .claude/settings.local.json (não vai pro git): libera a pasta de projetos escolhida acima.
    # Fica separado de .claude/settings.json de propósito — esse é compartilhado entre quem usa o Sêneca.
    $settingsLocal = [ordered]@{ permissions = [ordered]@{ allow = @() } }
    if (Test-Path ".claude\settings.local.json") {
        $existente = Get-Content ".claude\settings.local.json" -Raw | ConvertFrom-Json
        $settingsLocal.permissions.allow = @($existente.permissions.allow)
    }
    $settingsLocal.permissions.additionalDirectories = @($workspace -replace '\\', '/')
    $settingsLocal | ConvertTo-Json -Depth 10 | Set-Content -Path ".claude\settings.local.json" -Encoding UTF8
    "Perfil salvo em memoria\perfil.md. Pasta de projetos liberada (só pra você): $workspace"
} else {
    "memoria\perfil.md já existe — não mexi. Para refazer, apague esse arquivo e rode de novo."
}

if (-not (Test-Path "config\elevenlabs.json")) { Copy-Item "config\elevenlabs.exemplo.json" "config\elevenlabs.json" }

Titulo "Claude Code"
if (Tem claude) {
    "Encontrei o Claude Code instalado. Se ainda não entrou com sua conta, rode 'claude' nesta pasta uma vez e faça login."
} else {
    "Não achei o comando 'claude' no PATH — tudo bem, o 'npm install' já trouxe o necessário em app/node_modules."
    "Se ainda não tem o Claude Code configurado, rode 'npx claude' nesta pasta uma vez e faça login com sua conta."
}

Titulo "Pronto"
"Para ligar o Sêneca agora:"
"  app\.venv\Scripts\pythonw.exe app\seneca_app.pyw"
"Isso abre o Centro de Comando e cria sozinho os atalhos na Área de Trabalho e no menu Iniciar."
"Quer que ele ligue sozinho com o Windows? Copie o atalho 'Sêneca' da Área de Trabalho para a pasta de inicialização"
"(Win+R, digite shell:startup, Enter, cole o atalho lá)."
$abrir = Read-Host "`nAbrir o Sêneca agora? (s/n)"
if ($abrir -eq "s") { Start-Process (Join-Path $raiz ".venv\Scripts\pythonw.exe") -ArgumentList "`"$raiz\app\seneca_app.pyw`"" }
