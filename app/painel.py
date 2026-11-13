"""Painel do Sêneca: servidor local (127.0.0.1) que mostra o que ele está fazendo.

- /                 página do painel (painel.html)
- /img/<nome>.jpg   imagens do painel (app/img)
- /api/estado       estado da bandeja (ouvindo, pensando...) e o pedido atual
- /api/historico    pedidos feitos ao Sêneca, com os passos de cada um
- /api/delegadas    tarefas delegadas ao Claude (status, se ainda está rodando)
- /api/delegada     passo a passo ao vivo de uma tarefa delegada
- POST /api/parar   para uma tarefa delegada em andamento
- POST /api/abrir   abre o relatório .md
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP = Path(__file__).resolve().parent
DADOS = APP / "dados"
ATIVIDADE = DADOS / "atividade.jsonl"     # escrito pelo runner do claude_code (ao vivo)
HISTORICO = DADOS / "historico.jsonl"     # escrito pela bandeja (o que foi pedido)
DELEGADAS = APP.parent / "tarefas"
PORTA = 8766
CEREBRO_OK = lambda: False                # a bandeja troca por cerebro.vivo
TOKEN = secrets.token_hex(8)              # só a página servida aqui consegue usar os POSTs

_lock = threading.Lock()


# ----------------------------------------------------------------- utilidades
def _ler_jsonl(caminho: Path, max_bytes: int = 3_000_000) -> list[dict]:
    try:
        with open(caminho, "rb") as f:
            f.seek(0, 2)
            tam = f.tell()
            f.seek(max(0, tam - max_bytes))
            bruto = f.read().decode("utf-8-sig", "replace")
    except FileNotFoundError:
        return []
    linhas = bruto.splitlines()
    if tam > max_bytes:
        linhas = linhas[1:]                       # primeira pode estar cortada
    saida = []
    for l in linhas:
        l = l.strip()
        if not l:
            continue
        try:
            saida.append(json.loads(l))
        except json.JSONDecodeError:
            pass
    return saida


def registrar_historico(evento: dict) -> None:
    DADOS.mkdir(parents=True, exist_ok=True)
    evento = {"t": time.time(), **evento}
    with _lock, open(HISTORICO, "a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")


def _processo_vivo(pid: int) -> bool:
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    codigo = ctypes.c_ulong()
    ok = k.GetExitCodeProcess(h, ctypes.byref(codigo))
    k.CloseHandle(h)
    return bool(ok) and codigo.value == 259      # STILL_ACTIVE


def _entrada(entrada) -> dict:
    if isinstance(entrada, dict):
        return entrada
    if isinstance(entrada, str):
        try:
            v = json.loads(entrada)
            return v if isinstance(v, dict) else {"valor": v}
        except json.JSONDecodeError:
            achado = {}
            for chave in ("query", "file_path", "command", "pattern", "url", "description", "id", "path"):
                m = re.search(rf'"{chave}"\s*:\s*"((?:[^"\\]|\\.)*)', entrada)
                if m:
                    achado[chave] = m.group(1).encode().decode("unicode_escape", "ignore")
            return achado
    return {}


def _base(p: str) -> str:
    return re.split(r"[\\/]", p.rstrip("\\/"))[-1] if p else ""


def descrever_ferramenta(nome: str, entrada) -> tuple[str, str, str]:
    """-> (nome do ícone desenhado no painel, título em pt-BR, detalhe)"""
    e = _entrada(entrada)
    curto = lambda s, n=140: (s[: n - 1] + "…") if s and len(s) > n else (s or "")
    n = nome or "?"
    if n.startswith("mcp__") and "notion" in n.lower():
        acao = n.split("__")[-1].replace("notion-", "")
        if acao == "search":
            return "livro", "Buscando no Notion", curto(e.get("query", ""))
        if acao == "fetch":
            return "livro", "Abrindo uma página do Notion", curto(e.get("id", "") or e.get("url", ""))
        if acao.startswith("query"):
            return "livro", "Consultando um banco do Notion", ""
        return "livro", "Notion: " + acao.replace("-", " "), ""
    if n.startswith("mcp__"):
        return "tomada", n.split("__")[-1].replace("-", " "), ""
    if n in ("Bash", "PowerShell"):
        cmd = e.get("command", "")
        if "tarefa.ps1" in cmd:
            m = re.search(r'-Tarefa\s+"([^"]+)', cmd)
            return "enviar", "Criando uma tarefa", curto(m.group(1) if m else "", 220)
        if "tarefas.ps1" in cmd:
            return "lista", "Conferindo as tarefas", ""
        return "terminal", "Rodando um comando", curto(e.get("description") or cmd)
    mapa = {
        "Read": ("arquivo", "Lendo", _base(e.get("file_path", ""))),
        "Write": ("lapis", "Escrevendo", _base(e.get("file_path", ""))),
        "Edit": ("lapis", "Editando", _base(e.get("file_path", ""))),
        "MultiEdit": ("lapis", "Editando", _base(e.get("file_path", ""))),
        "NotebookEdit": ("lapis", "Editando notebook", _base(e.get("notebook_path", ""))),
        "Glob": ("busca", "Procurando arquivos", curto(e.get("pattern", ""))),
        "Grep": ("busca", "Procurando no código", "" if re.search(r"[|\\()\[\]*+?^$]", e.get("pattern", "")) else curto(e.get("pattern", ""))),
        "WebSearch": ("globo", "Pesquisando na web", curto(e.get("query", ""))),
        "WebFetch": ("globo", "Abrindo uma página", curto(e.get("url", ""))),
        "Task": ("chip", "Chamando um ajudante", curto(e.get("description", ""))),
        "Agent": ("chip", "Chamando um ajudante", curto(e.get("description", ""))),
        "TodoWrite": ("lista", "Atualizando a lista de passos", ""),
        "ToolSearch": ("chave", "Carregando ferramentas", ""),
        "Skill": ("brilho", "Usando uma habilidade", curto(e.get("skill", ""))),
    }
    return mapa.get(n, ("chave", n, ""))


def _texto_resultado(conteudo) -> str:
    if isinstance(conteudo, list):
        partes = [c.get("text", "") for c in conteudo if isinstance(c, dict)]
        conteudo = " ".join(p for p in partes if p)
    if not isinstance(conteudo, str):
        conteudo = json.dumps(conteudo, ensure_ascii=False)
    conteudo = re.sub(r"\s+", " ", conteudo).strip()
    return conteudo[:300] + ("…" if len(conteudo) > 300 else "")


def _passo_ferramenta(t, ident, nome, entrada) -> dict:
    icone, titulo, detalhe = descrever_ferramenta(nome, entrada)
    return {"t": t, "tipo": "ferramenta", "id": ident, "nome": nome,
            "icone": icone, "titulo": titulo, "detalhe": detalhe}


# ----------------------------------------------------------------- Sêneca (runner)
def _runs() -> dict[str, dict]:
    runs: dict[str, dict] = {}
    for ev in _ler_jsonl(ATIVIDADE):
        rid = ev.get("run")
        if not rid:
            continue
        r = runs.setdefault(rid, {"run": rid, "inicio": ev.get("t"), "fim": None, "ok": None,
                                  "pedido": "", "resposta": "", "passos": []})
        tipo = ev.get("tipo")
        if tipo == "inicio":
            r["inicio"] = ev.get("t")
            r["pedido"] = ev.get("pedido", "")
        elif tipo == "ferramenta":
            r["passos"].append(_passo_ferramenta(ev.get("t"), ev.get("id"), ev.get("nome"),
                                                 ev.get("entrada")))
        elif tipo == "resultado":
            for p in reversed(r["passos"]):
                if p.get("id") == ev.get("id"):
                    p["ok"] = ev.get("ok", True)
                    p["saida"] = ev.get("saida", "")
                    m = re.search(r"Tarefa criada:\s*(.+?)\.md", ev.get("saida", ""))
                    if m:
                        p["delegada"] = _base(m.group(1))
                    break
        elif tipo == "texto":
            r["passos"].append({"t": ev.get("t"), "tipo": "texto", "texto": ev.get("texto", "")})
        elif tipo == "fim":
            r["fim"] = ev.get("t")
            r["ok"] = ev.get("ok")
            r["resposta"] = ev.get("resposta", "")
    return runs


def _pedido_limpo(prompt: str) -> str:
    m = re.search(r"Nova fala d[oa] \S+[^:]*:\s*(.+)$", prompt, re.S)
    if m:
        return m.group(1).strip()
    return re.sub(r"^\(Conversa por voz:[^)]*\)\s*", "", prompt).strip()


def historico(n: int = 60) -> list[dict]:
    runs = _runs()
    usados: set[str] = set()
    itens: dict[str, dict] = {}
    for ev in _ler_jsonl(HISTORICO):
        if not ev.get("id") or not ev.get("t"):
            continue
        i = itens.setdefault(ev["id"], {"id": ev["id"], "origem": "voz", "inicio": ev["t"],
                                       "fim": None, "pedido": "", "resposta": "",
                                       "status": "pensando", "passos": []})
        if ev.get("tipo") == "pedido":
            i["pedido"] = ev.get("texto", "")
            i["inicio"] = ev["t"]
            i["origem"] = ev.get("origem", "voz")
        elif ev.get("tipo") == "resposta":
            i["resposta"] = ev.get("texto", "")
            i["fim"] = ev["t"]
            i["status"] = "ok"
        elif ev.get("tipo") == "erro":
            i["resposta"] = ev.get("texto", "")
            i["fim"] = ev["t"]
            i["status"] = "erro"
    # liga cada pedido à execução do Claude que aconteceu durante ele
    # consultas internas do painel (ex.: ler o Notion) não são conversas
    ordenados = sorted((r for r in runs.values() if "[[painel]]" not in (r["pedido"] or "")),
                       key=lambda r: r["inicio"] or 0)
    for i in itens.values():
        # o Claude começa segundos depois do pedido (antes, ainda pode estar subindo o servidor)
        limite = min(i["fim"] or i["inicio"] + 120, i["inicio"] + 120)
        for r in ordenados:
            if r["run"] in usados or not r["inicio"]:
                continue
            if i["inicio"] - 2 <= r["inicio"] <= limite + 1:
                i["passos"] = r["passos"]
                usados.add(r["run"])
                break
    # execuções que não vieram da voz (ex.: app no navegador)
    for r in ordenados:
        if r["run"] in usados:
            continue
        itens["run-" + r["run"]] = {
            "id": "run-" + r["run"], "origem": "app", "inicio": r["inicio"], "fim": r["fim"],
            "pedido": _pedido_limpo(r["pedido"]), "resposta": r["resposta"],
            "status": "pensando" if r["fim"] is None else ("ok" if r["ok"] else "erro"),
            "passos": r["passos"],
        }
    lista = sorted(itens.values(), key=lambda x: x["inicio"] or 0, reverse=True)
    # se a execução morreu sem "fim" há muito tempo, não fique "pensando" para sempre
    for i in lista:
        if i["status"] == "ok" and i["passos"] and i["passos"][-1].get("tipo") == "texto" and \
                i["passos"][-1]["texto"].strip()[:200] == (i["resposta"] or "").strip()[:200]:
            i["passos"] = i["passos"][:-1]                  # não repete a resposta nos passos
        if i["status"] == "pensando" and time.time() - (i["inicio"] or 0) > 900:
            i["status"] = "erro"
            i["resposta"] = i["resposta"] or "(sem resposta)"
    return lista[:n]


# ----------------------------------------------------------------- tarefas delegadas
def _campo(md: str, nome: str) -> str:
    m = re.search(rf"\*\*{nome}:\*\*\s*([^\r\n]+)", md)
    return m.group(1).strip() if m else ""


def _secao(md: str, titulo: str) -> str:
    m = re.search(rf"^## {titulo}\s*\n(.*?)(?=^## |\Z)", md, re.S | re.M)
    return m.group(1).strip() if m else ""


def _info_delegada(md_path: Path) -> dict:
    md = md_path.read_text(encoding="utf-8-sig", errors="replace")
    nome = md_path.stem
    status = _campo(md, "Status") or "?"
    pid_f = md_path.with_suffix(".pid")
    rodando = False
    if status.startswith("em andamento") and pid_f.exists():
        try:
            rodando = _processo_vivo(int(pid_f.read_text().strip()))
        except Exception:
            rodando = False
    elif status.startswith("em andamento"):
        # sem .pid (versão antiga): considera rodando se o log mexeu há pouco
        log = md_path.with_suffix(".log.jsonl")
        ref = log if log.exists() else md_path
        rodando = time.time() - ref.stat().st_mtime < 600
    if status.startswith("em andamento") and not rodando:
        status = "interrompida"
    titulo = re.sub(r"^\d{4}-\d{2}-\d{2}_\d{4}-", "", nome).replace("-", " ")
    return {
        "nome": nome, "titulo": titulo, "status": status, "rodando": rodando,
        "sessao": _campo(md, "Sessão Claude"),
        "inicio": _campo(md, "Início"), "pasta": _campo(md, "Pasta"),
        "pedido": _secao(md, "Pedido"), "mtime": md_path.stat().st_mtime,
        "tem_log": md_path.with_suffix(".log.jsonl").exists(),
        "inicio_t": md_path.stat().st_ctime,
    }


def delegadas(n: int = 60) -> list[dict]:
    if not DELEGADAS.exists():
        return []
    arqs = sorted(DELEGADAS.glob("*.md"), key=lambda p: p.name, reverse=True)[:n]
    saida = []
    for a in arqs:
        try:
            saida.append(_info_delegada(a))
        except Exception:
            pass
    return saida


def _seguro(nome: str) -> Path | None:
    if not re.fullmatch(r"[0-9A-Za-z_\-]+", nome or ""):
        return None
    p = DELEGADAS / f"{nome}.md"
    return p if p.exists() else None


def delegada(nome: str) -> dict | None:
    md_path = _seguro(nome)
    if not md_path:
        return None
    info = _info_delegada(md_path)
    md = md_path.read_text(encoding="utf-8-sig", errors="replace")
    info["resultado"] = _secao(md, "Resultado")
    passos: list[dict] = []
    final = None
    for ev in _ler_jsonl(md_path.with_suffix(".log.jsonl"), max_bytes=6_000_000):
        tipo = ev.get("type")
        t = ev.get("_t")
        if tipo == "system" and ev.get("subtype") == "init":
            passos.append({"tipo": "info", "texto": f"Claude começou ({ev.get('model', '')}) em {ev.get('cwd', '')}"})
        elif tipo == "assistant":
            for b in (ev.get("message") or {}).get("content") or []:
                if b.get("type") == "text" and b.get("text", "").strip():
                    passos.append({"tipo": "texto", "texto": b["text"].strip()[:1500]})
                elif b.get("type") == "tool_use":
                    passos.append(_passo_ferramenta(t, b.get("id"), b.get("name"), b.get("input")))
        elif tipo == "user":
            conteudo = (ev.get("message") or {}).get("content")
            if not isinstance(conteudo, list):
                continue
            for b in conteudo:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    for p in reversed(passos):
                        if p.get("id") == b.get("tool_use_id"):
                            p["ok"] = not b.get("is_error")
                            p["saida"] = _texto_resultado(b.get("content"))
                            break
        elif tipo == "result":
            final = {"ok": not ev.get("is_error"), "texto": ev.get("result", ""),
                     "segundos": round((ev.get("duration_ms") or 0) / 1000),
                     "turnos": ev.get("num_turns"), "custo": ev.get("total_cost_usd")}
        elif tipo == "stderr":
            texto = ev.get("text", "")
            if not texto.startswith("Ignoring "):          # aviso de configuração, não interessa
                passos.append({"tipo": "aviso", "texto": texto[:400]})
    # a última fala do Claude é o próprio resultado: não repete na linha do tempo
    if final and passos and passos[-1].get("tipo") == "texto" and \
            passos[-1]["texto"].strip()[:200] == (final["texto"] or "").strip()[:200]:
        passos.pop()
    info["passos"] = passos
    info["final"] = final
    log = md_path.with_suffix(".log.jsonl")
    info["ult_t"] = log.stat().st_mtime if log.exists() else info["inicio_t"]
    info["n_passos"] = sum(1 for p in passos if p.get("tipo") == "ferramenta")
    # o que está acontecendo agora, em uma palavra para a tela
    pendente = next((p for p in reversed(passos) if p.get("tipo") == "ferramenta" and "ok" not in p), None)
    if not info["rodando"]:
        info["agora"] = None
    elif pendente:
        info["agora"] = {"tipo": "ferramenta", "icone": pendente.get("icone"), "titulo": pendente.get("titulo"),
                         "detalhe": pendente.get("detalhe")}
    elif any(p.get("tipo") in ("ferramenta", "texto") for p in passos):
        info["agora"] = {"tipo": "pensando"}
    else:
        info["agora"] = {"tipo": "comecando"}
    return info


def parar_delegada(nome: str) -> str:
    md_path = _seguro(nome)
    if not md_path:
        return "tarefa não encontrada"
    pid_f = md_path.with_suffix(".pid")
    if not pid_f.exists():
        return "essa tarefa não pode ser parada (sem PID)"
    try:
        pid = int(pid_f.read_text().strip())
    except ValueError:
        return "PID inválido"
    if _processo_vivo(pid):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    md = md_path.read_text(encoding="utf-8-sig", errors="replace")
    md = re.sub(r"\*\*Status:\*\* em andamento",
                f"**Status:** parada manualmente ({time.strftime('%H:%M')})", md)
    md = md.rstrip() + "\n\n_Tarefa parada pelo painel do Sêneca antes de terminar._\n"
    md_path.write_text(md, encoding="utf-8-sig")
    try:
        pid_f.unlink()    # arquivo de controle do próprio painel
    except OSError:
        pass
    return "ok"


# ----------------------------------------------------------------- sistema (monitor, clima, conexões)
_cache: dict = {"clima": ("", 0.0), "servidor": (False, 0.0), "uso": 0.0, "cpu": 0.0}


def _medir_cpu() -> None:
    """Mede sempre na mesma linha de execução: em cada linha nova, a 1ª leitura do psutil seria 0."""
    import psutil
    while True:
        _cache["cpu"] = psutil.cpu_percent(interval=2)


def _cidade_clima() -> str:
    try:
        return json.loads((APP / "config.json").read_text(encoding="utf-8")).get("cidade_clima", "").strip()
    except Exception:
        return ""


def _clima() -> str:
    texto, quando = _cache["clima"]
    cidade = _cidade_clima()
    if not cidade:
        return ""
    if time.time() - quando > 1800:
        _cache["clima"] = (texto, time.time())          # evita disparar duas vezes

        def buscar():
            try:
                r = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                     str(APP.parent / "scripts" / "clima.ps1"), cidade],
                    capture_output=True, timeout=40, creationflags=subprocess.CREATE_NO_WINDOW)
                linha = r.stdout.decode("utf-8", "replace").splitlines()[0]
                _cache["clima"] = (linha.replace(f"Agora em {cidade}: ", "").strip(), time.time())
            except Exception:
                pass
        threading.Thread(target=buscar, daemon=True).start()
    return texto


def uso() -> dict:
    """Utilização da assinatura (janelas de 5h e 7 dias), renovada a cada 5 min enquanto o painel está aberto.
    Sem dado recente, o painel esconde o indicador em vez de mostrar um número velho."""
    if time.time() - _cache["uso"] > 300:
        _cache["uso"] = time.time()                     # evita disparar duas vezes

        def buscar():
            import cerebro
            try:
                r = subprocess.run([cerebro._node(), "cerebro.mjs", "--uso"], cwd=APP, capture_output=True, timeout=60,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                falha = r.stderr.decode("utf-8", "replace")[:300] if r.returncode else ""
            except Exception as e:
                falha = str(e)
            if falha:
                with open(cerebro.ERROS, "a", encoding="utf-8") as f:
                    f.write(f"[uso] {falha}\n")
        threading.Thread(target=buscar, daemon=True).start()
    try:
        dados = json.loads((DADOS / "uso.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dados if time.time() - dados.get("atualizado", 0) < 1800 else {}


def sistema() -> dict:
    import psutil
    hoje = time.strftime("%Y-%m-%d")
    hist = [e for e in _ler_jsonl(HISTORICO) if e.get("tipo") == "pedido"]
    ativ = _ler_jsonl(ATIVIDADE)
    try:
        notas = sum(1 for _ in (APP.parent / "memoria").rglob("*.md"))
    except Exception:
        notas = 0
    dl = delegadas()
    return {
        "cpu": _cache["cpu"],
        "ram": psutil.virtual_memory().percent,
        "disco": psutil.disk_usage("D:\\").percent,
        "clima": _clima(),
        "servidor": CEREBRO_OK(),
        "notas": notas,
        "pedidos_hoje": sum(1 for e in hist if time.strftime("%Y-%m-%d", time.localtime(e["t"])) == hoje),
        "pedidos_total": len(hist),
        "ferramentas_hoje": sum(1 for e in ativ if e.get("tipo") == "ferramenta"
                                and time.strftime("%Y-%m-%d", time.localtime(e.get("t", 0))) == hoje),
        "delegadas_rodando": sum(1 for d in dl if d["rodando"]),
        "delegadas_total": len(dl),
    }


# ----------------------------------------------------------------- servidor HTTP
class Painel:
    def __init__(self, obter_estado, acoes: dict | None = None):
        self.obter_estado = obter_estado        # função -> dict
        self.acoes = acoes or {}                # funções da bandeja: perguntar, nova_conversa, config, reiniciar, falar
        self.ultimo_acesso = 0.0                # última vez que uma página aberta perguntou
        self.servidor = None

    def _get(self, rota: str, q: dict):
        import recursos as r
        import vozes as motor_voz
        if rota == "/api/estado":
            self.ultimo_acesso = time.time()
            # a janela aberta compara esta versão e se recarrega quando algo muda
            return {**self.obter_estado(), "versao": f"{TOKEN}-{(APP / 'painel.html').stat().st_mtime}"}
        tabela = {
            "/api/sistema": sistema,
            "/api/uso": uso,
            "/api/historico": lambda: historico(int(q.get("n", 60))),
            "/api/delegadas": delegadas,
            "/api/nucleo": r.nucleo,
            "/api/vozes": motor_voz.perfis,
            "/api/agentes": r.agentes,
            "/api/ferramentas": r.ferramentas,
            "/api/tarefas-locais": r.tarefas_locais,
            "/api/notion": lambda: r.notion(q.get("tipo", "tarefas"), q.get("forcar") == "1"),
            "/api/calendario": lambda: r.calendario(q.get("mes", ""), historico(500), delegadas(500)),
            "/api/memoria": r.memoria,
            "/api/busca": lambda: r.buscar(q.get("q", "")),
            "/api/conhecimento": r.conhecimento,
            "/api/fluxos": r.fluxos,
        }
        if rota == "/api/microfones":
            f = self.acoes.get("microfones")
            return f() if f else {"atual": "", "escolhido": "", "lista": []}
        if rota == "/api/delegada":
            return delegada(q.get("nome", "")) or {"erro": "não encontrada"}
        if rota == "/api/nota":
            return r.nota(q.get("c", "")) or {"erro": "não encontrada"}
        f = tabela.get(rota)
        return f() if f else None

    def _post(self, rota: str, q: dict, corpo: dict):
        import recursos as r
        nome = q.get("nome") or corpo.get("nome", "")
        a = self.acoes
        if rota == "/api/parar":
            return {"resultado": parar_delegada(nome)}
        if rota == "/api/apagar":
            p = _seguro(nome)
            rodando = bool(p) and _info_delegada(p)["rodando"]
            return {"resultado": r.apagar_delegada(nome, rodando)}
        if rota == "/api/abrir-claude":
            p = _seguro(nome)
            info = _info_delegada(p) if p else {}
            if info.get("rodando"):                  # importar agora congelaria a sessão no app
                abrir_lista_claude()
                return {"resultado": "ok", "ao_vivo": True}
            ok = bool(p) and abrir_no_claude(info.get("sessao", ""), esperar=0)
            return {"resultado": "ok" if ok else "sem sessão do Claude"}
        if rota == "/api/abrir":
            p = _seguro(nome)
            if p:
                os.startfile(p)
            return {"resultado": "ok" if p else "não encontrada"}
        if rota == "/api/perguntar":
            f = a.get("perguntar")
            ok = f(corpo.get("texto", "")) if f else False
            return {"resultado": "ok" if ok else "o Sêneca está ocupado ou a bandeja está desligada"}
        if rota == "/api/nova-conversa" and a.get("nova_conversa"):
            a["nova_conversa"]()
            return {"resultado": "ok"}
        if rota == "/api/config" and a.get("config"):
            return {"resultado": a["config"](corpo.get("chave", ""), bool(corpo.get("valor")))}
        if rota == "/api/reiniciar-servidor" and a.get("reiniciar"):
            threading.Thread(target=a["reiniciar"], daemon=True).start()
            return {"resultado": "reiniciando"}
        if rota == "/api/abrir-sessao" and a.get("abrir_sessao"):
            a["abrir_sessao"]()
            return {"resultado": "ok"}
        if rota == "/api/reiniciar-bandeja" and a.get("reiniciar_bandeja"):
            a["reiniciar_bandeja"]()
            return {"resultado": "reiniciando"}
        if rota == "/api/definir-voz" and a.get("definir_voz"):
            return {"resultado": a["definir_voz"](corpo.get("voz", ""))}
        if rota == "/api/definir-microfone" and a.get("definir_microfone"):
            return {"resultado": a["definir_microfone"](corpo.get("nome", ""))}
        if rota == "/api/ouvir-amostra" and a.get("ouvir_amostra"):
            return {"resultado": a["ouvir_amostra"](corpo.get("voz", ""))}
        if rota == "/api/delegar":
            return {"resultado": r.delegar(corpo.get("pasta", ""), corpo.get("tarefa", ""))}
        if rota == "/api/tarefa-local":
            return {"resultado": r.tarefa_local(corpo.get("acao", ""), int(corpo.get("linha", -1)),
                                                corpo.get("texto", ""), corpo.get("secao", "Hoje"))}
        if rota == "/api/nota-salvar":
            return {"resultado": r.salvar_nota(corpo.get("c", ""), corpo.get("texto", ""))}
        if rota == "/api/nota-abrir":
            p = r.caminho_nota(corpo.get("c", ""))
            if p:
                os.startfile(p)
            return {"resultado": "ok" if p else "não encontrada"}
        if rota == "/api/abrir-pasta":
            p = r.pasta_permitida(corpo.get("caminho", ""))
            if p:
                os.startfile(p)
            return {"resultado": "ok" if p else "pasta inválida"}
        if rota == "/api/fluxo-executar":
            m = r.montar_fluxo(corpo.get("id", ""), corpo.get("texto", ""), corpo.get("pasta", ""), historico(200))
            if not m:
                return {"resultado": "fluxo não encontrado"}
            if m["tipo"] == "perguntar":
                f = a.get("perguntar")
                ok = f(m["prompt"]) if f else False
                return {"resultado": "ok" if ok else "o Sêneca está ocupado agora", "tipo": "perguntar"}
            return {"resultado": r.delegar(m["pasta"], m["prompt"], m["nome"]), "tipo": "delegar"}
        if rota == "/api/fluxo-salvar":
            return {"resultado": r.salvar_fluxo(corpo)}
        if rota == "/api/fluxo-apagar":
            return {"resultado": r.apagar_fluxo(corpo.get("id", ""))}
        return None

    def iniciar(self) -> bool:
        painel = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, dados, codigo=200):
                corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)

            def do_GET(self):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                try:
                    if u.path in ("/", "/index.html"):
                        html = (APP / "painel.html").read_text(encoding="utf-8")
                        corpo = html.replace("__TOKEN__", TOKEN).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Content-Length", str(len(corpo)))
                        self.end_headers()
                        self.wfile.write(corpo)
                    elif re.fullmatch(r"/img/[a-z0-9-]+\.jpg", u.path) and (APP / u.path[1:]).exists():
                        corpo = (APP / u.path[1:]).read_bytes()
                        self.send_response(200)
                        self.send_header("Content-Type", "image/jpeg")
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Content-Length", str(len(corpo)))
                        self.end_headers()
                        self.wfile.write(corpo)
                    else:
                        dados = painel._get(u.path, q)
                        if dados is None:
                            self.send_error(404)
                        else:
                            self._json(dados)
                except Exception as e:
                    self._json({"erro": str(e)}, 500)

            def do_POST(self):
                if self.headers.get("X-Painel") != TOKEN:
                    self.send_error(403)
                    return
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    corpo = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
                    dados = painel._post(u.path, q, corpo if isinstance(corpo, dict) else {})
                    if dados is None:
                        self.send_error(404)
                    else:
                        self._json(dados)
                except Exception as e:
                    self._json({"erro": str(e)}, 500)

        try:
            self.servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), H)
        except OSError:
            return False
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        threading.Thread(target=_medir_cpu, daemon=True).start()
        return True

    def aberto_recentemente(self) -> bool:
        return time.time() - self.ultimo_acesso < 4


def abrir_lista_claude() -> None:
    """Traz o app do Claude para a frente, na aba Code: as tarefas em andamento ficam ao vivo na barra lateral."""
    os.startfile("claude://claude.ai/epitaxy")


def abrir_no_claude(sessao: str, esperar: float = 30) -> bool:
    """Importa uma sessão JÁ TERMINADA no app do Claude e abre ela lá."""
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", sessao or ""):
        return False
    projetos = Path.home() / ".claude" / "projects"
    fim = time.time() + esperar
    while not list(projetos.glob(f"*/{sessao}.jsonl")) and time.time() < fim:
        time.sleep(1)                       # o Claude cria o transcrito no 1º segundo
    os.startfile(f"claude://resume?session={sessao}")
    return True


def abrir_janela(ancora: str = "") -> None:
    """Abre o programa do Sêneca (janela própria); se faltar, o Edge em modo app."""
    app = APP / "seneca_app.pyw"
    pythonw = Path(os.sys.executable).with_name("pythonw.exe")
    if app.exists() and pythonw.exists():
        subprocess.Popen([str(pythonw), str(app)] + ([ancora] if ancora else []), cwd=str(APP))
        return
    url = f"http://127.0.0.1:{PORTA}/" + (f"#{ancora}" if ancora else "")
    for edge in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                 r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if os.path.exists(edge):
            subprocess.Popen([edge, f"--app={url}", "--window-size=1180,820"],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            return
    import webbrowser
    webbrowser.open(url)
