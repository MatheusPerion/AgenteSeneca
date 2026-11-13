"""O Sêneca é o Claude: mantém uma sessão contínua do Claude Code aberta, pronta para o próximo pedido."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

APP = Path(__file__).resolve().parent
SESSAO_ARQ = APP / "dados" / "sessao.json"
ERROS = APP / "dados" / "cerebro-erros.log"
OCIOSA = 8 * 3600        # depois de 8 h parado, começa uma conversa nova
SEM_JANELA = subprocess.CREATE_NO_WINDOW


def _node() -> str:
    return shutil.which("node") or r"C:\Program Files\nodejs\node.exe"


def perguntar_unico(prompt: str, timeout: int = 300) -> str:
    """Consulta avulsa, fora da conversa (ex.: o painel lendo o Notion)."""
    r = subprocess.run([_node(), "cerebro.mjs", "--unico"], cwd=APP, input=prompt, capture_output=True, text=True,
                       encoding="utf-8", timeout=timeout, creationflags=SEM_JANELA)
    linhas = [l for l in r.stdout.splitlines() if l.startswith("{")]
    if not linhas:
        raise RuntimeError((r.stderr or "o Claude não respondeu")[:300])
    dados = json.loads(linhas[-1])
    if not dados.get("ok"):
        raise RuntimeError(dados.get("resposta", "falhou"))
    return dados["resposta"]


class Cerebro:
    def __init__(self, log=lambda _: None):
        self.log = log
        self.proc: subprocess.Popen | None = None
        self.vez = threading.Lock()          # um pedido por vez na conversa
        self.aberto = threading.Lock()       # protege o processo
        self.espera: dict | None = None
        self.sessao = ""
        self.retomou = False
        self.turnos = 0
        self.ultimo = 0.0

    # ---------- sessão
    def _ler(self) -> dict:
        try:
            return json.loads(SESSAO_ARQ.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _gravar(self):
        SESSAO_ARQ.parent.mkdir(parents=True, exist_ok=True)
        SESSAO_ARQ.write_text(json.dumps({"id": self.sessao, "ultimo": self.ultimo, "turnos": self.turnos}), encoding="utf-8")

    def vivo(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def iniciar(self, nova: bool = False):
        with self.aberto:
            self._encerrar()
            g = self._ler()
            continuar = not nova and g.get("id") and g.get("turnos", 0) > 0 and time.time() - g.get("ultimo", 0) < OCIOSA
            self.sessao = g["id"] if continuar else str(uuid.uuid4())
            self.turnos = g.get("turnos", 0) if continuar else 0
            self.ultimo = g.get("ultimo", 0) if continuar else time.time()
            self.retomou = bool(continuar)
            self._gravar()
            env = dict(os.environ, SENECA_SESSAO=self.sessao, SENECA_RETOMAR="1" if continuar else "0")
            ERROS.parent.mkdir(parents=True, exist_ok=True)
            self.proc = subprocess.Popen([_node(), "cerebro.mjs"], cwd=APP, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=open(ERROS, "a", encoding="utf-8"), text=True, encoding="utf-8", bufsize=1,
                                         creationflags=SEM_JANELA)
            threading.Thread(target=self._ouvir, args=(self.proc,), daemon=True).start()
            self.log(f"cérebro ligado (sessão {self.sessao[:8]}, {'continuando' if continuar else 'nova'})")

    def _encerrar(self):
        p, self.proc = self.proc, None
        if p is None:
            return
        try:
            p.stdin.close()
            p.wait(5)
        except Exception:
            p.kill()

    def parar(self):
        with self.aberto:
            self._encerrar()

    def nova_conversa(self):
        self.iniciar(nova=True)

    def reiniciar(self):
        self.iniciar()

    def _ouvir(self, proc):
        for linha in proc.stdout:
            if not linha.startswith("{"):
                continue
            try:
                dados = json.loads(linha)
            except ValueError:
                continue
            esp = self.espera
            if esp and dados.get("id") == esp["id"]:
                esp["dados"] = dados
                esp["fim"].set()
        esp = self.espera                     # o processo caiu no meio de um pedido
        if esp and proc is self.proc:
            esp["fim"].set()

    # ---------- conversa
    def _enviar(self, texto: str, timeout: int) -> dict | None:
        ident = uuid.uuid4().hex[:8]
        esp = {"id": ident, "fim": threading.Event(), "dados": None}
        self.espera = esp
        try:
            self.proc.stdin.write(json.dumps({"id": ident, "prompt": texto}, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except Exception:
            return None
        if not esp["fim"].wait(timeout):
            self.log("cérebro: tempo esgotado; religando")
            self.iniciar()
            raise TimeoutError("o Claude demorou demais para responder")
        return esp["dados"]

    def perguntar(self, texto: str, timeout: int = 600) -> str:
        with self.vez:
            if time.time() - self.ultimo > OCIOSA and self.turnos:
                self.iniciar(nova=True)
            elif not self.vivo():
                self.iniciar()
            dados = self._enviar(texto, timeout)
            if (dados is None or not dados.get("ok")) and self.retomou:
                # a sessão antiga não pôde ser retomada: começa outra e tenta de novo
                self.log(f"cérebro: não retomou a sessão ({(dados or {}).get('resposta', 'processo caiu')[:120]})")
                self.iniciar(nova=True)
                dados = self._enviar(texto, timeout)
            if dados is None:
                self.iniciar()
                raise RuntimeError("o Claude parou de responder; já religuei, tente de novo")
            if not dados.get("ok"):
                raise RuntimeError(dados.get("resposta", "falhou"))
            self.retomou = False
            self.turnos += 1
            self.ultimo = time.time()
            self.sessao = dados.get("sessao") or self.sessao
            self._gravar()
            return (dados.get("resposta") or "").strip()
