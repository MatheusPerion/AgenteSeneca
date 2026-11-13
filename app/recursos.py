"""Funções das seções do Centro de Comando do Sêneca.

Núcleo de IA, Agentes, Tarefas (Obsidian + Notion), Calendário, Memória,
Base de conhecimento, Ferramentas e habilidades, Fluxos, e apagar tarefas do Claude.
Tudo local; o Notion é lido pelo próprio Claude e guardado em cache.
"""
from __future__ import annotations

import asyncio
import ctypes
import json
import re
import subprocess
import threading
import time
from ctypes import wintypes
from pathlib import Path

import edge_tts

import cerebro
import vozes as vozes_do_seneca

APP = Path(__file__).resolve().parent
DADOS = APP / "dados"
RAIZ = APP.parent
MEMORIA = RAIZ / "memoria"
DELEGADAS = RAIZ / "tarefas"
MARCA_INTERNA = "[[painel]]"          # pedidos do próprio painel (não entram no histórico)
SEM_JANELA = subprocess.CREATE_NO_WINDOW
BANCO_NOTION_PADRAO = "Development Tracker"


def _app_config() -> dict:
    try:
        return json.loads((APP / "config.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def workspace() -> Path:
    """Pasta onde ficam os seus projetos (editável; ajuste 'workspace' em app/config.json)."""
    cfg_valor = _app_config().get("workspace", "")
    return Path(cfg_valor) if cfg_valor else RAIZ.parent


def _ler(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig", errors="replace")


def _frontmatter(texto: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---", texto, re.S)
    if not m:
        return {}
    d = {}
    for linha in m.group(1).splitlines():
        if ":" in linha:
            k, v = linha.split(":", 1)
            d[k.strip()] = v.strip()
    return d


# ----------------------------------------------------------------- projetos (projetos.md)
def projetos() -> list[dict]:
    try:
        texto = _ler(MEMORIA / "projetos.md")
    except FileNotFoundError:
        return []
    saida = []
    for bloco in re.split(r"^## ", texto, flags=re.M)[1:]:
        linhas = bloco.splitlines()
        nome = linhas[0].strip()
        corpo = "\n".join(linhas[1:])
        caminhos = re.findall(r"[A-Z]:\\[^\s(),]+", corpo)
        caminho = caminhos[0] if caminhos else ""
        status = re.search(r"\*\*Status:\*\*\s*(.+)", corpo)
        notas = re.search(r"\*\*Notas:\*\*\s*(.+)", corpo)
        subs = []
        for nm, desc in re.findall(r"^\s+-\s+`([^`]+)`\s*[—-]\s*(.+)$", corpo, re.M):
            subs.append({"nome": nm, "descricao": desc.strip(), "caminho": str(Path(caminho) / nm) if caminho else ""})
        saida.append({"nome": nome, "caminho": caminho, "caminhos": caminhos,
                      "status": status.group(1).strip() if status else "",
                      "notas": notas.group(1).strip() if notas else "", "subpastas": subs})
    return saida


def pastas_de_projeto() -> list[dict]:
    """Opções para 'onde o Claude vai trabalhar'."""
    vistos, opcoes = set(), []
    for p in projetos():
        for c in p["caminhos"]:
            if c not in vistos and Path(c).exists():
                vistos.add(c)
                opcoes.append({"rotulo": f"{p['nome']} — {Path(c).name}", "caminho": c})
        for s in p["subpastas"]:
            if s["caminho"] and s["caminho"] not in vistos and Path(s["caminho"]).exists():
                vistos.add(s["caminho"])
                opcoes.append({"rotulo": f"{p['nome']} — {s['nome']}", "caminho": s["caminho"]})
    return opcoes


def pasta_permitida(caminho: str) -> Path | None:
    try:
        p = Path(caminho).resolve()
    except Exception:
        return None
    w = workspace()
    if p.exists() and p.is_dir() and (p == w or w in p.parents):
        return p
    return None


# ----------------------------------------------------------------- núcleo de IA
def _permissoes() -> dict:
    try:
        return json.loads((RAIZ / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]
    except Exception:
        return {}


def nucleo() -> dict:
    app_cfg = _app_config()
    perms = _permissoes()
    return {
        "voz_atual": vozes_do_seneca.atual(app_cfg)["nome"],
        "atalho": app_cfg.get("atalho", "ctrl_r"),
        "permitidas": len(perms.get("allow", [])),
        "pastas_extras": perms.get("additionalDirectories", []),
        "raiz": str(RAIZ),
        "notion_banco": app_cfg.get("notion_banco", BANCO_NOTION_PADRAO),
        "notion_eu": app_cfg.get("notion_eu", "").lower(),
    }


# ----------------------------------------------------------------- agentes, ferramentas, habilidades
def _descricao_script(p: Path) -> str:
    for linha in _ler(p).splitlines()[:4]:
        linha = linha.strip().lstrip("\ufeff")
        if linha.startswith("#"):
            return linha.lstrip("# ").strip()
    return ""


def ferramentas() -> dict:
    perms = _permissoes()
    grupos: dict[str, list[str]] = {}

    def add(grupo, rotulo):
        lista = grupos.setdefault(grupo, [])
        if rotulo not in lista:
            lista.append(rotulo)

    add("Projetos", f"Editar arquivos em {workspace()}")
    nomes = {"Read": "Ler arquivos", "Glob": "Procurar arquivos", "Grep": "Procurar dentro de arquivos"}
    web = {"WebSearch": "Pesquisar na web", "WebFetch": "Abrir p\u00e1ginas da web"}
    pc = {"abrir.ps1": "Abrir aplicativos e sites", "pesquisar.ps1": "Pesquisar no seu navegador", "fechar.ps1": "Fechar aplicativos",
          "clima.ps1": "Ver o clima"}
    for f in perms.get("allow", []):
        if f in nomes:
            add("Arquivos e mem\u00f3ria", nomes[f])
        elif f in web:
            add("Web", web[f])
        elif "notion" in f.lower():
            add("Notion (s\u00f3 leitura)", f.split("notion-")[-1].replace("-", " "))
        elif f in ("Task", "Agent"):
            add("Tarefas", "Chamar subagentes")
        elif "tarefa.ps1" in f:
            add("Tarefas", "Criar tarefas no Claude")
        elif "tarefas.ps1" in f:
            add("Tarefas", "Ver o andamento das tarefas")
        elif "winget" in f:
            add("Computador", "Instalar programas que você pedir")
        elif re.search(r"\(git (add|commit|push|pull)", f):
            add("Projetos", "Commit, push e pull quando você pedir")
        elif re.search(r"\((git|dotnet|npm|python)", f):
            add("Projetos", {"git": "Consultar o git", "dotnet": "Compilar e testar .NET", "npm": "Rodar scripts npm", "python": "Testes Python"}[re.search(r"\((git|dotnet|npm|python)", f).group(1)])
        else:
            for script, rotulo in pc.items():
                if script in f:
                    add("Computador", rotulo)
    habilidades = []
    for s in sorted((RAIZ / ".claude" / "skills").glob("*/SKILL.md")):
        fm = _frontmatter(_ler(s))
        habilidades.append({"nome": fm.get("name", s.parent.name), "descricao": fm.get("description", "")})
    scripts = [{"nome": s.stem, "descricao": _descricao_script(s), "desligado": False} for s in sorted((RAIZ / "scripts").glob("*.ps1"))]
    return {"grupos": grupos, "bloqueadas": perms.get("deny", []), "habilidades": habilidades, "scripts": scripts,
            "total": sum(len(v) for v in grupos.values()) + len(habilidades)}


def agentes() -> dict:
    sub = []
    for a in sorted((RAIZ / ".claude" / "agents").glob("*.md")):
        fm = _frontmatter(_ler(a))
        sub.append({"nome": fm.get("name", a.stem), "descricao": fm.get("description", ""),
                    "ferramentas": fm.get("tools", "")})
    return {"subagentes": sub, "pastas": pastas_de_projeto()}


# ----------------------------------------------------------------- acoes rápidas (lista fechada)


def _ps(script: Path, *args, timeout=40) -> str:
    r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
                       capture_output=True, timeout=timeout, creationflags=SEM_JANELA)
    return (r.stdout or b"").decode("utf-8", "replace").strip() or (r.stderr or b"").decode("utf-8", "replace").strip()


def acao_rapida(nome: str, arg: str = "") -> str:
    if nome == "clima":
        cidade = re.sub(r"[^A-Za-z\-]", "", arg) or _app_config().get("cidade_clima", "") or "Goiania"
        return _ps(RAIZ / "scripts" / "clima.ps1", cidade)
    return "Ação desconhecida."


# ----------------------------------------------------------------- tarefas do Obsidian (tarefas.md)
TAREFAS_MD = MEMORIA / "tarefas.md"


def tarefas_locais() -> dict:
    try:
        linhas = _ler(TAREFAS_MD).splitlines()
    except FileNotFoundError:
        return {"secoes": []}
    secoes, atual = [], None
    for i, l in enumerate(linhas):
        m = re.match(r"^##\s+(.+)", l)
        if m:
            atual = {"nome": m.group(1).strip(), "itens": []}
            secoes.append(atual)
            continue
        m = re.match(r"^\s*-\s+\[( |x|X)\]\s+(.*)$", l)
        if m and atual is not None:
            atual["itens"].append({"linha": i, "feito": m.group(1) != " ", "texto": m.group(2).strip()})
    return {"secoes": secoes, "pendentes": sum(1 for s in secoes for t in s["itens"] if not t["feito"])}


def tarefa_local(acao: str, linha: int = -1, texto: str = "", secao: str = "Hoje") -> str:
    linhas = _ler(TAREFAS_MD).splitlines()
    if acao == "alternar":
        if not (0 <= linha < len(linhas)) or not re.match(r"^\s*-\s+\[( |x|X)\]", linhas[linha]):
            return "linha inválida"
        if re.match(r"^\s*-\s+\[ \]", linhas[linha]):
            linhas[linha] = re.sub(r"\[ \]", "[x]", linhas[linha], count=1)
        else:
            linhas[linha] = re.sub(r"\[(x|X)\]", "[ ]", linhas[linha], count=1)
    elif acao == "adicionar":
        texto = texto.strip().replace("\n", " ")
        if not texto:
            return "texto vazio"
        idx = next((i for i, l in enumerate(linhas) if re.match(rf"^##\s+{re.escape(secao)}\s*$", l)), None)
        if idx is None:
            linhas += ["", f"## {secao}"]
            idx = len(linhas) - 1
        fim = idx + 1
        while fim < len(linhas) and not linhas[fim].startswith("## "):
            fim += 1
        while fim - 1 > idx and not linhas[fim - 1].strip():
            fim -= 1
        # tira o "-" vazio de seção sem itens
        if fim - 1 > idx and linhas[fim - 1].strip() == "-":
            linhas.pop(fim - 1)
            fim -= 1
        linhas.insert(fim, f"- [ ] {texto}")
    elif acao == "apagar":
        # só apaga se a linha ainda for esta tarefa concluída (o arquivo pode ter mudado no Obsidian)
        m = re.match(r"^\s*-\s+\[[xX]\]\s+(.*)$", linhas[linha]) if 0 <= linha < len(linhas) else None
        if not m or m.group(1).strip() != texto.strip():
            return "a tarefa mudou no arquivo; atualize a tela e tente de novo"
        del linhas[linha]
    elif acao == "limpar":
        linhas = [l for l in linhas if not re.match(r"^\s*-\s+\[[xX]\]", l)]
    else:
        return "ação inválida"
    TAREFAS_MD.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return "ok"


# ----------------------------------------------------------------- memória e base de conhecimento
def _rel(p: Path) -> str:
    return p.relative_to(MEMORIA).as_posix()


DOCS = {"doc:leia-me": RAIZ / "LEIA-ME.md", "doc:personalidade": RAIZ / "CLAUDE.md"}


def caminho_nota(c: str) -> Path | None:
    if c in DOCS:
        return DOCS[c]
    try:
        p = (MEMORIA / c).resolve()
    except Exception:
        return None
    if p.suffix == ".md" and p.exists() and MEMORIA.resolve() in p.parents:
        return p
    return None


def memoria() -> list[dict]:
    grupos = {"perfil.md": "Quem sou", "objetivos.md": "Quem sou", "tarefas.md": "Rotina",
              "projetos.md": "Trabalho", "respostas-prontas.md": "Trabalho"}
    saida = []
    for p in sorted(MEMORIA.rglob("*.md")):
        if any(parte.startswith(".") for parte in p.relative_to(MEMORIA).parts):
            continue
        rel = _rel(p)
        grupo = "Diário" if rel.startswith("diario/") else "Notas" if rel.startswith("notas/") else grupos.get(rel, "Outros")
        saida.append({"c": rel, "titulo": p.stem.replace("-", " "), "grupo": grupo, "mtime": p.stat().st_mtime,
                      "tamanho": p.stat().st_size})
    return saida


def nota(c: str) -> dict | None:
    p = caminho_nota(c)
    if not p:
        return None
    return {"c": c, "titulo": p.stem.replace("-", " "), "texto": _ler(p), "caminho": str(p),
            "editavel": not c.startswith("doc:"), "mtime": p.stat().st_mtime}


def salvar_nota(c: str, texto: str) -> str:
    p = caminho_nota(c)
    if not p or c.startswith("doc:"):
        return "não pode editar"
    if len(texto) > 400_000:
        return "texto grande demais"
    p.write_text(texto.replace("\r\n", "\n"), encoding="utf-8")
    return "ok"


def buscar(q: str) -> list[dict]:
    q = q.strip().lower()
    if len(q) < 2:
        return []
    achados = []
    for item in memoria():
        texto = _ler(MEMORIA / item["c"])
        for i, linha in enumerate(texto.splitlines()):
            if q in linha.lower():
                achados.append({"c": item["c"], "titulo": item["titulo"], "linha": i + 1, "trecho": linha.strip()[:200]})
                if len(achados) > 80:
                    return achados
    return achados


def conhecimento() -> dict:
    notas = [m for m in memoria() if m["grupo"] == "Notas"]
    docs = [{"c": k, "titulo": k.split(":", 1)[1].replace("-", " "), "existe": v.exists()} for k, v in DOCS.items()]
    return {"projetos": projetos(), "notas": notas, "docs": [d for d in docs if d["existe"]],
            "respostas": "respostas-prontas.md" if (MEMORIA / "respostas-prontas.md").exists() else ""}


# ----------------------------------------------------------------- vozes disponíveis (edge-tts)


# ----------------------------------------------------------------- Notion, lido pelo próprio Sêneca
_notion_lock = threading.Lock()
_notion_estado: dict[str, str] = {}
def PEDIDOS_NOTION() -> dict:
    banco = _app_config().get("notion_banco", BANCO_NOTION_PADRAO)
    return {
        "tarefas": (
            f"Busque no Notion, no banco '{banco}', as tarefas que NÃO estão concluídas. "
            "Responda SOMENTE com um JSON válido, sem nenhum texto antes ou depois e sem markdown, no formato "
            '{"tarefas":[{"titulo":"","status":"","prioridade":"","responsavel":"","sprint":"","prazo":"AAAA-MM-DD ou vazio","url":""}]}'
        ),
        "agenda": (
            "Liste os eventos do meu calendário (ferramenta notion-calendar-list-events) de hoje até daqui a 30 dias, "
            "e também tarefas do Notion que tenham data. Responda SOMENTE com um JSON válido, sem texto antes ou depois e sem markdown, "
            'no formato {"eventos":[{"titulo":"","inicio":"AAAA-MM-DDTHH:MM","fim":"","local":"","origem":"calendário ou tarefa"}],"aviso":""}. '
            "Se não houver calendário conectado, devolva eventos vazio e explique em aviso."
        ),
    }


def _arquivo_notion(tipo: str) -> Path:
    return DADOS / f"notion-{tipo}.json"


def notion(tipo: str, forcar: bool = False) -> dict:
    if tipo not in PEDIDOS_NOTION():
        return {"erro": "tipo inválido"}
    arq = _arquivo_notion(tipo)
    try:
        cache = json.loads(arq.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    velho = time.time() - cache.get("quando", 0) > 3600      # sozinho, no máximo 1 vez por hora
    if (forcar or velho or not cache) and _notion_estado.get(tipo) != "consultando":
        _notion_estado[tipo] = "consultando"
        threading.Thread(target=_consultar_notion, args=(tipo,), daemon=True).start()
    return {**cache, "estado": _notion_estado.get(tipo, "ok")}


def _consultar_notion(tipo: str):
    try:
        with _notion_lock:
            texto = cerebro.perguntar_unico(f"{MARCA_INTERNA} {PEDIDOS_NOTION()[tipo]}")
        ini, fim = texto.find("{"), texto.rfind("}")
        dados = json.loads(texto[ini:fim + 1])
        DADOS.mkdir(parents=True, exist_ok=True)
        _arquivo_notion(tipo).write_text(json.dumps({"quando": time.time(), "dados": dados}, ensure_ascii=False),
                                         encoding="utf-8")
        _notion_estado[tipo] = "ok"
    except Exception as e:
        _notion_estado[tipo] = f"erro: {e}"


# ----------------------------------------------------------------- calendário
def calendario(mes: str, hist: list[dict], dl: list[dict]) -> dict:
    if not re.fullmatch(r"\d{4}-\d{2}", mes or ""):
        mes = time.strftime("%Y-%m")
    dias: dict[str, dict] = {}

    def dia(d: str) -> dict:
        return dias.setdefault(d, {"conversas": [], "delegadas": [], "diario": False, "eventos": [], "prazos": []})

    for h in hist:
        d = time.strftime("%Y-%m-%d", time.localtime(h.get("inicio") or 0))
        if d.startswith(mes):
            dia(d)["conversas"].append({"id": h["id"], "hora": time.strftime("%H:%M", time.localtime(h["inicio"])),
                                        "pedido": h.get("pedido", "")[:140]})
    for t in dl:
        d = (t.get("inicio") or "")[:10]
        if d.startswith(mes):
            dia(d)["delegadas"].append({"nome": t["nome"], "titulo": t["titulo"], "status": t["status"]})
    for p in (MEMORIA / "diario").glob(f"{mes}-*.md"):
        dia(p.stem)["diario"] = True
    agenda = notion("agenda")
    for e in (agenda.get("dados") or {}).get("eventos", []):
        d = (e.get("inicio") or "")[:10]
        if d.startswith(mes):
            dia(d)["eventos"].append(e)
    tarefas_n = notion("tarefas")
    for t in (tarefas_n.get("dados") or {}).get("tarefas", []):
        d = (t.get("prazo") or "")[:10]
        if d.startswith(mes):
            dia(d)["prazos"].append(t)
    return {"mes": mes, "dias": dias, "estado_agenda": agenda.get("estado"),
            "aviso_agenda": (agenda.get("dados") or {}).get("aviso", "")}


# ----------------------------------------------------------------- delegar e apagar tarefas do Claude
def delegar(pasta: str, tarefa: str, nome: str = "") -> str:
    p = pasta_permitida(pasta)
    tarefa = (tarefa or "").strip()
    if not p:
        return f"erro: pasta inválida (precisa existir dentro de {workspace()})"
    if len(tarefa) < 8:
        return "erro: descreva melhor a tarefa"
    args = ["-Pasta", str(p), "-Tarefa", tarefa]
    if nome:
        args += ["-Nome", re.sub(r"[^a-z0-9\-]", "", nome.lower())[:40]]
    return _ps(RAIZ / "scripts" / "tarefa.ps1", *args, timeout=30)


class _SHFILEOP(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", ctypes.c_void_p),
                ("pTo", ctypes.c_void_p), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]


def para_lixeira(arquivos: list[Path]) -> bool:
    """Manda para a Lixeira do Windows (dá para recuperar)."""
    arquivos = [str(a) for a in arquivos if a.exists()]
    if not arquivos:
        return True
    texto = "\0".join(arquivos) + "\0\0"
    buf = (ctypes.c_wchar * len(texto))(*texto)
    op = _SHFILEOP(None, 3, ctypes.cast(buf, ctypes.c_void_p), None,
                   0x0040 | 0x0010 | 0x0004 | 0x0400, False, None, None)   # ALLOWUNDO|NOCONFIRM|SILENT|NOERRORUI
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not op.fAnyOperationsAborted


def apagar_delegada(nome: str, rodando: bool) -> str:
    if not re.fullmatch(r"[0-9A-Za-z_\-]+", nome or ""):
        return "nome inválido"
    if rodando:
        return "essa tarefa ainda está rodando: pare antes de apagar"
    base = DELEGADAS / nome
    arquivos = [Path(f"{base}{ext}") for ext in (".md", ".log.jsonl", ".pid", ".tarefa.txt")]
    if not arquivos[0].exists():
        return "tarefa não encontrada"
    return "ok" if para_lixeira(arquivos) else "não consegui mover para a Lixeira"


# ----------------------------------------------------------------- fluxos (rotinas prontas)
FLUXOS_ARQ = DADOS / "fluxos.json"
FLUXOS_PADRAO = [
    {"id": "briefing", "nome": "Briefing do dia", "icone": "☀", "tipo": "perguntar", "pede": "",
     "descricao": "Tarefas do Notion, suas tarefas do Obsidian e projetos, num resumo curto.",
     "prompt": "Faça meu briefing do dia: tarefas abertas no Notion, minhas tarefas em "
               "memoria/tarefas.md e o status dos projetos. Curto e direto."},
    {"id": "hoje", "nome": "O que tenho pra hoje?", "icone": "◷", "tipo": "perguntar", "pede": "",
     "descricao": "Lê suas tarefas e o Notion e diz o que priorizar hoje.",
     "prompt": "O que eu tenho pra hoje? Olhe minhas tarefas (Obsidian e Notion) e diga as 3 prioridades."},
    {"id": "status-claude", "nome": "Status das tarefas do Claude", "icone": "⚑", "tipo": "perguntar", "pede": "",
     "descricao": "Resume o andamento de tudo que foi delegado.",
     "prompt": "Como estão as tarefas?"},
    {"id": "encerrar", "nome": "Encerrar o dia", "icone": "☾", "tipo": "delegar", "pede": "", "pasta": str(RAIZ),
     "descricao": "O Claude escreve no seu diário o resumo do dia e as pendências de amanhã.",
     "prompt": "Encerre o meu dia. Leia a pasta memoria (tarefas, projetos) e os relatórios de hoje na pasta "
               "tarefas. Escreva em memoria/diario/{data}.md "
               "(acrescente ao final se já existir) um resumo do dia e as pendências para amanhã, no formato Obsidian. "
               "Conversas de hoje com o Sêneca:\n{conversas}"},
    {"id": "revisar", "nome": "Revisar um projeto", "icone": "⚖", "tipo": "delegar", "pede": "projeto",
     "descricao": "O Claude revisa o código procurando bugs e melhorias, sem alterar nada.",
     "prompt": "Revise o código desta pasta procurando bugs, problemas de segurança e melhorias de clareza. "
               "NÃO altere nenhum arquivo: entregue um relatório priorizado (crítico, importante, sugestão), com arquivo e linha."},
    {"id": "pesquisar", "nome": "Pesquisar a fundo", "icone": "⌕", "tipo": "delegar", "pede": "texto", "pasta": str(RAIZ),
     "descricao": "O Claude pesquisa um assunto na web e entrega um relatório com fontes.",
     "prompt": "Use o subagente pesquisador para pesquisar a fundo e responder com fontes: {texto}"},
]


def fluxos() -> list[dict]:
    try:
        meus = json.loads(FLUXOS_ARQ.read_text(encoding="utf-8"))
    except Exception:
        meus = []
    return [dict(f, proprio=False) for f in FLUXOS_PADRAO] + [dict(f, proprio=True) for f in meus]


def salvar_fluxo(f: dict) -> str:
    nome = (f.get("nome") or "").strip()
    prompt = (f.get("prompt") or "").strip()
    tipo = f.get("tipo")
    if not nome or len(prompt) < 8 or tipo not in ("perguntar", "delegar"):
        return "preencha nome, tipo e o pedido"
    try:
        meus = json.loads(FLUXOS_ARQ.read_text(encoding="utf-8"))
    except Exception:
        meus = []
    pede = f.get("pede") if f.get("pede") in ("", "texto", "projeto") else ""
    novo = {"id": "meu-" + str(int(time.time())), "nome": nome[:60], "icone": "✦", "tipo": tipo, "pede": pede,
            "descricao": (f.get("descricao") or "").strip()[:160], "prompt": prompt[:4000],
            "pasta": f.get("pasta") or str(RAIZ)}
    meus.append(novo)
    DADOS.mkdir(parents=True, exist_ok=True)
    FLUXOS_ARQ.write_text(json.dumps(meus, ensure_ascii=False, indent=1), encoding="utf-8")
    return "ok"


def apagar_fluxo(fid: str) -> str:
    try:
        meus = json.loads(FLUXOS_ARQ.read_text(encoding="utf-8"))
    except Exception:
        return "não encontrado"
    resto = [f for f in meus if f.get("id") != fid]
    if len(resto) == len(meus):
        return "só dá para apagar fluxos criados por você"
    FLUXOS_ARQ.write_text(json.dumps(resto, ensure_ascii=False, indent=1), encoding="utf-8")
    return "ok"


def montar_fluxo(fid: str, texto: str, pasta: str, hist: list[dict]) -> dict | None:
    f = next((x for x in fluxos() if x["id"] == fid), None)
    if not f:
        return None
    hoje = time.strftime("%Y-%m-%d")
    conversas = "\n".join(f"- {time.strftime('%H:%M', time.localtime(h['inicio']))} Você: {h.get('pedido', '')[:200]} | "
                          f"Sêneca: {h.get('resposta', '')[:200]}" for h in reversed(hist)
                          if time.strftime("%Y-%m-%d", time.localtime(h.get("inicio") or 0)) == hoje) or "(nenhuma)"
    prompt = f["prompt"].replace("{data}", hoje).replace("{conversas}", conversas).replace("{texto}", texto.strip())
    if f["pede"] == "texto" and "{texto}" not in f["prompt"] and texto.strip():
        prompt += "\n\n" + texto.strip()
    destino = pasta if f["pede"] == "projeto" else f.get("pasta", str(RAIZ))
    return {"tipo": f["tipo"], "prompt": prompt, "pasta": destino, "nome": f["id"]}
