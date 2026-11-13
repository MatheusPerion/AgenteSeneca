# Clima atual e previsão (wttr.in, sem chave). Uso: .\clima.ps1 [Cidade]   (padrão: Goiania)
param([string]$Cidade = 'Goiania')
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$c = [uri]::EscapeDataString($Cidade)
try {
    $j = Invoke-RestMethod -TimeoutSec 10 "https://wttr.in/$($c)?format=j1&lang=pt"
    $a = $j.current_condition[0]
    "Agora em ${Cidade}: $($a.lang_pt[0].value), $($a.temp_C) graus (sensação $($a.FeelsLikeC)), umidade $($a.humidity)%."
    foreach ($d in $j.weather | Select-Object -First 2) {
        $chuva = ($d.hourly | Measure-Object -Property chanceofrain -Maximum).Maximum
        "$($d.date): mínima $($d.mintempC), máxima $($d.maxtempC) graus, chance de chuva até $chuva%."
    }
} catch {
    "Não consegui consultar o clima agora ($($_.Exception.Message))."
}
