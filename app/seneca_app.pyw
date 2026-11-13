"""Sêneca — Centro de Comando (programa de janela própria).

Abre o painel numa janela nativa do Windows (pywebview + WebView2), com ícone próprio
na barra de tarefas. Se o Sêneca da bandeja (voz) não estiver rodando, inicia ele também.
Uso: pythonw seneca_app.pyw [d=<tarefa>]
"""
from __future__ import annotations

import base64
import ctypes
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parent
ICONE = APP / "seneca.ico"
PORTA = 8766
TITULO = "Sêneca — Centro de Comando"
URL = f"http://127.0.0.1:{PORTA}/"
PYTHONW = Path(sys.executable).with_name("pythonw.exe")

FUNDO = "#050504"
_TELA = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><style>
html,body{height:100%;margin:0;overflow:hidden}
body{display:grid;place-items:center start;background:radial-gradient(900px 600px at 30% 45%,rgba(86,71,38,.34),transparent 70%),__FUNDO__;
font:600 13px "Segoe UI",system-ui,sans-serif;color:__COR__;user-select:none}
.marmore{position:fixed;top:0;bottom:0;right:0;aspect-ratio:1;transform:translateX(12%);background:url(data:image/jpeg;base64,__MARMORE__) center/cover no-repeat;mix-blend-mode:screen;
-webkit-mask-image:linear-gradient(90deg,transparent 4%,#000 34%),linear-gradient(0deg,transparent 3%,#000 24%);-webkit-mask-composite:source-in}
.selo{position:relative;width:208px;height:208px;margin:0 auto 26px;display:grid;place-items:center}
.selo img{width:168px;height:168px;filter:drop-shadow(0 0 22px rgba(242,202,110,.35))}
.selo svg{position:absolute;inset:0;animation:__ANIMA__}
@keyframes giro{to{transform:rotate(360deg)}}
b{display:block;font:700 34px Cinzel,Georgia,serif;letter-spacing:9px;margin-right:-9px;color:#f2ca6e;text-shadow:0 0 18px rgba(242,202,110,.4)}
p{margin:12px 0 0;letter-spacing:3px}
</style></head><body><div class="marmore"></div><div style="position:relative;z-index:1;text-align:center;margin-left:clamp(48px,13vw,240px)">
<div class="selo"><img alt="" src="data:image/png;base64,__SELO__"><svg viewBox="0 0 208 208"><circle cx="104" cy="104" r="100" fill="none"
stroke="#f2ca6e" stroke-opacity=".3" stroke-dasharray="3 9"/><path d="M104 4a100 100 0 0 1 70.7 29.3" fill="none" stroke="__COR_ARCO__" stroke-width="3" stroke-linecap="round"/></svg></div>
<b>SÊNECA</b><p>__TEXTO__</p></div></body></html>"""


def tela(texto: str, erro: bool = False) -> str:
    """Tela de abertura, no mesmo tema verde do painel."""
    trocas = {"__FUNDO__": FUNDO, "__COR__": "#ff6170" if erro else "#9e9788", "__COR_ARCO__": "#ff6170" if erro else "#f2ca6e",
              "__ANIMA__": "none" if erro else "giro 1.6s linear infinite", "__TEXTO__": texto,
              "__SELO__": base64.b64encode((APP / "seneca.png").read_bytes()).decode(),
              "__MARMORE__": base64.b64encode((APP / "img" / "marmore.jpg").read_bytes()).decode()}
    html = _TELA
    for marca, valor in trocas.items():
        html = html.replace(marca, valor)
    return html


def painel_no_ar() -> bool:
    try:
        return urllib.request.urlopen(URL + "api/estado", timeout=1.5).status == 200
    except Exception:
        return False


def trazer_para_frente() -> bool:
    u = ctypes.windll.user32
    h = u.FindWindowW(None, TITULO)
    if not h:
        return False
    u.ShowWindow(h, 9)            # SW_RESTORE
    u.SetForegroundWindow(h)
    return True


def iniciar_bandeja():
    subprocess.Popen([str(PYTHONW), str(APP / "bandeja.py")], cwd=str(APP.parent),
                     creationflags=0x00000008 | 0x00000200)   # DETACHED + NEW_PROCESS_GROUP


def main():
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\SenecaCentroDeComando")
    if ctypes.windll.kernel32.GetLastError() == 183:   # já aberto: só traz a janela
        trazer_para_frente()
        return
    # ícone próprio na barra de tarefas (não agrupa com o Python)
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Seneca.CentroDeComando")

    import webview

    ancora = sys.argv[1] if len(sys.argv) > 1 else ""
    destino = URL + (f"#{ancora}" if ancora else "")
    pronto = painel_no_ar()
    janela = webview.create_window(
        TITULO, destino if pronto else None, html=None if pronto else tela("INICIANDO O NÚCLEO…"),
        width=1440, height=900, min_size=(960, 620), background_color=FUNDO,
    )

    def ao_abrir():
        if not pronto:
            iniciar_bandeja()
            for _ in range(60):
                if painel_no_ar():
                    janela.load_url(destino)
                    return
                time.sleep(1)
            janela.load_html(tela("NÃO CONSEGUI INICIAR — VEJA app\\log.txt", erro=True))

    webview.start(ao_abrir, private_mode=False, storage_path=str(APP / "dados" / "webview"), icon=str(ICONE))
    del mutex


if __name__ == "__main__":
    main()
