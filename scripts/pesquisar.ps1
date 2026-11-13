# Sêneca: abre uma pesquisa no navegador padrão do Matheus.
# Uso: scripts/pesquisar.ps1 -Termo "receita de pão de queijo" [-Onde google|youtube|imagens|mapas|github|wikipedia|noticias|compras]
# Só monta um endereço https de busca e abre no navegador; não envia nada nem preenche formulários.
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Termo,
    [ValidateSet('google', 'youtube', 'imagens', 'mapas', 'github', 'wikipedia', 'noticias', 'compras')][string]$Onde = 'google'
)
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$t = $Termo.Trim()
if (-not $t) { 'Diga o que pesquisar.'; exit 1 }
$q = [uri]::EscapeDataString($t)
$url = switch ($Onde) {
    'google'    { "https://www.google.com/search?q=$q" }
    'youtube'   { "https://www.youtube.com/results?search_query=$q" }
    'imagens'   { "https://www.google.com/search?tbm=isch&q=$q" }
    'mapas'     { "https://www.google.com/maps/search/$q" }
    'github'    { "https://github.com/search?q=$q" }
    'wikipedia' { "https://pt.wikipedia.org/w/index.php?search=$q" }
    'noticias'  { "https://news.google.com/search?q=$q&hl=pt-BR&gl=BR&ceid=BR:pt-419" }
    'compras'   { "https://www.google.com/search?tbm=shop&q=$q" }
}
Start-Process $url
$nomes = @{ google = 'no Google'; youtube = 'no YouTube'; imagens = 'nas imagens do Google'; mapas = 'no Google Maps'
            github = 'no GitHub'; wikipedia = 'na Wikipédia'; noticias = 'nas notícias'; compras = 'no Google Shopping' }
"Abri a pesquisa por '$t' $($nomes[$Onde]) no seu navegador."
