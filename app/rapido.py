"""Caminho rápido do Sêneca: comandos simples executados na hora, sem acordar o Claude.

Reconhece só frases claras de "abrir app/site" e "pesquisar em <lugar>". Qualquer dúvida
devolve None e o pedido segue normalmente para o Claude. Mesmos limites do scripts/abrir.ps1:
apenas apps do menu Iniciar e sites https; nada de caminhos ou comandos.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import threading
import time
import unicodedata
from urllib.parse import quote

_apps: list[tuple[str, str, str]] = []        # (nome normalizado, nome, AppID)

APELIDOS = {
    "navegador": "brave", "internet": "brave", "browser": "brave",
    "vscode": "visual studio code", "vs code": "visual studio code", "code": "visual studio code",
    "explorador": "explorador de arquivos", "arquivos": "explorador de arquivos", "pastas": "explorador de arquivos",
    "lol": "league of legends", "league": "league of legends", "riot": "cliente riot", "tft": "league of legends",
    "notas": "obsidian", "memoria": "obsidian",
}
SITES = {
    "youtube": "https://www.youtube.com", "gmail": "https://mail.google.com", "google": "https://www.google.com",
    "github": "https://github.com", "notion": "https://www.notion.so", "netflix": "https://www.netflix.com",
    "twitch": "https://www.twitch.tv", "instagram": "https://www.instagram.com",
    # exemplos de sites pedidos com frequência por voz — adicione ou troque pelos seus
    "metatft": "https://www.metatft.com", "tactics tools": "https://tactics.tools", "tft tactics": "https://tactics.tools",
    "tft teticus": "https://tactics.tools",
}
NOME_SITE = {"youtube": "YouTube", "gmail": "Gmail", "google": "Google", "github": "GitHub", "notion": "Notion",
             "netflix": "Netflix", "twitch": "Twitch", "instagram": "Instagram", "metatft": "MetaTFT",
             "tactics tools": "Tactics.tools", "tft tactics": "Tactics.tools", "tft teticus": "Tactics.tools"}

LUGAR = (r"google maps|google|nav[ei]gador|internet|brave|web|youtube|you tube|github|git hub|"
         r"wikip[eé]dia|mapas?|maps|not[ií]cias|imagens")
LUGARES = {"google": "google", "navegador": "google", "navigador": "google", "internet": "google", "brave": "google", "web": "google",
           "youtube": "youtube", "you tube": "youtube", "github": "github", "git hub": "github",
           "wikipedia": "wikipedia", "google maps": "mapas", "mapa": "mapas", "mapas": "mapas", "maps": "mapas",
           "noticias": "noticias", "imagens": "imagens"}
BUSCA = {
    "google": ("https://www.google.com/search?q={}", "no Google"),
    "youtube": ("https://www.youtube.com/results?search_query={}", "no YouTube"),
    "github": ("https://github.com/search?q={}", "no GitHub"),
    "wikipedia": ("https://pt.wikipedia.org/w/index.php?search={}", "na Wikipédia"),
    "mapas": ("https://www.google.com/maps/search/{}", "no Google Maps"),
    "noticias": ("https://news.google.com/search?q={}&hl=pt-BR&gl=BR&ceid=BR:pt-419", "nas notícias"),
    "imagens": ("https://www.google.com/search?tbm=isch&q={}", "nas imagens do Google"),
}
NAVEGADOR = {"navegador", "internet", "browser", "brave"}
# palavras comuns que não devem casar com o meio do nome de um app ("abre a tarefa" ≠ Gerenciador de Tarefas)
_GENERICAS = {"tarefa", "projeto", "arquivo", "pasta", "relatorio", "nota", "pagina", "documento", "site",
              "email", "agenda", "conversa", "memoria", "painel", "configurac", "configuracoe", "sistema", "jogo"}

_PREFIXO = re.compile(
    r"^\s*(?:(?:[sc][eêé]n[ieí]c[ao]|ei|oi|[oô]|por favor|favor|eu\s+)?[,.:!]*\s+|"
    r"(?:eu\s+)?(?:quero|queria|preciso)\s+que\s+(?:voc[eê]\s+)?|voc[eê]\s+(?:pode\s+|poderia\s+|consegue\s+)?|"
    r"(?:pode|poderia|consegue)\s+(?:me\s+)?|me\s+)", re.I)
_NOME = re.compile(r"^\s*[sc][eêé]n[ieí]c[ao]\b[,.:!]*\s*", re.I)
_FIM = re.compile(r"[\s,.!?;:]*(?:\b(?:pra mim|para mim|por favor|a[ií]|agora|rapidinho|obrigad[oa]|valeu|de novo|novamente)\b)?[\s,.!?;:]*$", re.I)
# "abriu": o Whisper costuma ouvir assim quando você diz "abre"
_ABRIR = re.compile(r"^(?:abre|abra|abrir|abriu|inicia|inicie|iniciar|executa|execute)\s+(?:(?:o|a|os|as|meu|minha|meus|minhas)\s+)?(.+)$", re.I)
_NO_NAVEGADOR = re.compile(r"[\s,]+(?:no|na|pelo|pela|em)\s+(?:nav[ei]gador|internet|brave)\b.*$", re.I)
_FINALIDADE = re.compile(r"\s+(?:para|pra)\s+.*$", re.I)          # "abre X para ver as builds"
_DOMINIO = re.compile(r"(?:https?://)?[\w-]+(?:\.[\w-]+)+(?:/\S*)?", re.I)
_BUSCAR = re.compile(r"^(pesquis\w*|procur\w*|busc\w*|toca|toque|tocar|coloca|coloque|p[oõ]e|bota)\s+(.+)$", re.I)
_LUGAR_ANTES = re.compile(rf"^(?:no|na|em|pelo|pela)\s+({LUGAR})\s+(?:(?:por|sobre)\s+)?(.+)$", re.I)
_LUGAR_DEPOIS = re.compile(rf"^(.+?)\s+(?:no|na|em|pelo|pela)\s+({LUGAR})$", re.I)
_DIVISOR = re.compile(r"\s+(?:e|para|pra)\s+(?=(?:pesquis|procur|busc|abr|toc|toqu|coloc))", re.I)


def normalizar(s: str) -> str:
    d = unicodedata.normalize("NFD", s.lower())
    d = "".join(c for c in d if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", d)).strip()


def _carregar_apps():
    cmd = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
           "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress")
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", cmd], capture_output=True, timeout=60,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    lista = json.loads(r.stdout.decode("utf-8", "replace"))
    _apps[:] = [(normalizar(a["Name"]), a["Name"], a["AppID"]) for a in lista
                if not re.search(r"uninstall|desinstalar|support center|leia-me|readme", a["Name"], re.I)]


def iniciar():
    """Mantém a lista de apps pronta na memória (consultar a cada pedido custaria mais de 1 s)."""
    def laco():
        while True:
            try:
                _carregar_apps()
            except Exception:
                pass
            time.sleep(900)
    threading.Thread(target=laco, daemon=True).start()


def _achar_app(alvo: str):
    n = APELIDOS.get(alvo, alvo)
    candidatos = [a for a in _apps if a[0] == n]
    if not candidatos and len(n) >= 3:
        candidatos = [a for a in _apps if a[0].startswith(n)]
    if not candidatos and len(n) >= 4 and n.rstrip("s") not in _GENERICAS:
        candidatos = [a for a in _apps if f" {n}" in f" {a[0]}"]     # só em começo de palavra
    return min(candidatos, key=lambda a: len(a[0])) if candidatos else None


def _limpar(frase: str) -> str:
    atual = frase.strip()
    while True:
        novo = _FIM.sub("", atual).strip()
        if novo == atual:
            return novo
        atual = novo


def _sem_prefixo(frase: str) -> str:
    atual = _NOME.sub("", frase)
    while True:
        novo = _PREFIXO.sub("", atual, count=1).lstrip(" ,.:!")
        if novo == atual or not novo:
            return atual
        atual = novo


def _url_de_dominio(cru: str, chave: str = "") -> dict:
    url = cru if cru.lower().startswith("http") else f"https://{cru}"
    return {"tipo": "url", "alvo": url, "frase": f"Abri {cru} no navegador", "chave": chave}


def _achar_site(alvo: str) -> str | None:
    """Nome de site conhecido, tolerando o que o Whisper entende errado ("metadeft" = MetaTFT)."""
    if alvo in SITES:
        return alvo
    junto = alvo.replace(" ", "")
    por_nome = {k.replace(" ", ""): k for k in SITES}
    if junto in por_nome:
        return por_nome[junto]
    parecidos = difflib.get_close_matches(junto, list(por_nome), n=1, cutoff=0.8) if len(junto) >= 5 else []
    return por_nome[parecidos[0]] if parecidos else None


def _abrir(trecho: str):
    m = _ABRIR.match(trecho)
    if not m:
        return None
    alvo_cru = _limpar(m.group(1))
    no_navegador = bool(_NO_NAVEGADOR.search(alvo_cru))
    alvo_cru = _limpar(_FINALIDADE.sub("", _NO_NAVEGADOR.sub("", alvo_cru)))
    alvo = normalizar(alvo_cru)
    if not alvo or len(alvo.split()) > 4:
        return None
    if _DOMINIO.fullmatch(alvo_cru):
        return _url_de_dominio(alvo_cru, alvo)
    if not no_navegador:
        app = _achar_app(alvo)
        if app:
            return {"tipo": "app", "alvo": app[2], "frase": f"Abri {app[1]}", "chave": alvo}
    site = _achar_site(alvo)
    if site:
        return {"tipo": "url", "alvo": SITES[site], "frase": f"Abri {NOME_SITE[site]} no navegador", "chave": site}
    if no_navegador:                               # site que não conheço: a busca abre na hora
        return {"tipo": "url", "alvo": BUSCA["google"][0].format(quote(alvo_cru, safe="")),
                "frase": f"Não conheço esse site, então pesquisei {alvo_cru} no Google", "chave": ""}
    return None


def _buscar(trecho: str, lugar_implicito: str | None):
    m = _BUSCAR.match(trecho)
    if not m:
        return None
    verbo, resto = m.group(1).lower(), _limpar(m.group(2))
    lugar, termo = None, None
    a = _LUGAR_ANTES.match(resto)
    d = _LUGAR_DEPOIS.match(resto)
    if a:
        lugar, termo = a.group(1), a.group(2)
    elif d:
        termo, lugar = d.group(1), d.group(2)
    elif lugar_implicito:
        lugar, termo = lugar_implicito, resto
    elif _DOMINIO.fullmatch(resto) and verbo.startswith(("pesquis", "procur", "busc")):
        return _url_de_dominio(resto)               # "pesquisa metatft.com"
    if not lugar or not termo:
        return None                                 # sem lugar claro: quem decide é o Claude
    onde = LUGARES.get(normalizar(lugar))
    termo = re.sub(r"^(?:por|sobre)\s+", "", _limpar(termo), flags=re.I).strip()
    if not onde or len(termo) < 2:
        return None
    if not verbo.startswith(("pesquis", "procur", "busc")) and onde != "youtube":
        return None                                 # "toca X" só faz sentido no YouTube
    molde, rotulo = BUSCA[onde]
    return {"tipo": "url", "alvo": molde.format(quote(termo, safe="")), "frase": f"Pesquisei {termo} {rotulo}", "chave": ""}


def interpretar(texto: str) -> list[dict] | None:
    """Transforma a frase em ações, ou None se não for um comando simples e claro."""
    if not texto or len(texto) > 200 or "whatsapp" in normalizar(texto).replace(" ", ""):
        return None                                 # WhatsApp segue desligado: o Claude explica
    if "?" in texto and re.search(r"\babriu\b", texto, re.I):
        return None                                 # "abriu o navegador?" é pergunta, não comando
    texto = re.sub(r",?\s*\bpor favor\b,?", " ", texto, flags=re.I)
    frase = _limpar(_sem_prefixo(texto))
    acoes: list[dict] = []
    lugar = None
    for trecho in _DIVISOR.split(frase):
        trecho = _sem_prefixo(_limpar(trecho))
        acao = _abrir(trecho)
        if acao:
            if acao["chave"] in NAVEGADOR:
                lugar = "google"
            elif acao["chave"] in ("youtube", "google"):
                lugar = acao["chave"]
        else:
            acao = _buscar(trecho, lugar)
        if not acao:
            return None
        acoes.append(acao)
    # "abre o navegador e pesquisa X": a pesquisa já abre o navegador
    if len(acoes) > 1 and any(not a["chave"] and a["alvo"].startswith("http") for a in acoes):
        acoes = [a for a in acoes if a["chave"] not in NAVEGADOR and a["chave"] not in ("youtube", "google")]
    return acoes or None


def _executar(acao: dict):
    alvo = acao["alvo"]
    if acao["tipo"] == "url" or re.match(r"^https?://", alvo) or (re.match(r"^[A-Za-z]:\\", alvo) and os.path.exists(alvo)):
        os.startfile(alvo)
    else:
        os.startfile(f"shell:AppsFolder\\{alvo}")


def tentar(texto: str) -> str | None:
    """Executa o comando, se for simples. Devolve a confirmação, ou None para seguir ao Claude."""
    acoes = interpretar(texto)
    if not acoes:
        return None
    try:
        for a in acoes:
            _executar(a)
    except Exception:
        return None
    return " e ".join(a["frase"] if i == 0 else a["frase"][0].lower() + a["frase"][1:] for i, a in enumerate(acoes)) + "."
