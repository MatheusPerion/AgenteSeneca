# Sêneca: baixa as vozes locais (Piper, offline) em app/vozes. Sem internet depois de baixadas.
# Uso: scripts/baixar-vozes.ps1  (~60MB por voz; pode demorar)
# Opcional: sem rodar isso, o Sêneca funciona normalmente com as vozes online (edge-tts).
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$destino = Join-Path (Split-Path -Parent $PSScriptRoot) 'app\vozes'
New-Item -ItemType Directory -Force $destino | Out-Null

$vozes = @(
    @{ falante = 'faber'; qualidade = 'medium' }
    @{ falante = 'cadu'; qualidade = 'medium' }
    @{ falante = 'jeff'; qualidade = 'medium' }
    @{ falante = 'edresson'; qualidade = 'low' }
)
foreach ($v in $vozes) {
    $nome = "pt_BR-$($v.falante)-$($v.qualidade)"
    $base = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/$($v.falante)/$($v.qualidade)/$nome"
    foreach ($ext in '.onnx', '.onnx.json') {
        $arq = Join-Path $destino "$nome$ext"
        if (Test-Path $arq) { "$nome$ext já existe."; continue }
        "Baixando $nome$ext ..."
        try { Invoke-WebRequest -Uri "$base$ext" -OutFile $arq -UseBasicParsing }
        catch { "Falhou: $($_.Exception.Message)"; Remove-Item $arq -ErrorAction SilentlyContinue }
    }
}
"Pronto. Reinicie o Sêneca para as vozes aparecerem em Núcleo de IA → Trocar voz."
