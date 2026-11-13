"""Sêneca na bandeja do Windows: os ouvidos e a voz do Claude.

Segure o Ctrl DIREITO, fale e solte. Transcreve (faster-whisper), entrega à sessão contínua do Claude
(cerebro.py) e responde em voz (edge-tts) e numa notificação. Sem janela de cmd: rode com pythonw.exe.
"""
from __future__ import annotations

import ctypes
import json
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
import warnings
from pathlib import Path

# --- silêncio total para avisos de bibliotecas ---
os.environ.setdefault("HF_HUB_OFFLINE", "1")          # modelos já estão no cache
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ["PYTHONUTF8"] = "1"
warnings.filterwarnings("ignore")

APP = Path(__file__).resolve().parent
LOG = APP / "log.txt"
CONFIG = APP / "config.json"

# bibliotecas da NVIDIA instaladas no ambiente: a transcrição precisa delas no PATH
_NVIDIA = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
os.environ["PATH"] = os.pathsep.join(str(_NVIDIA / p / "bin") for p in ("cublas", "cudnn", "cuda_nvrtc")) + \
    os.pathsep + os.environ.get("PATH", "")

PADRAO = {
    "atalho": "ctrl_r",
    "voz": "pt-BR-AntonioNeural",
    "velocidade": "+0%",
    "tom": "-4Hz",
    "modelo_transcricao": "small",
    "dispositivo_transcricao": "auto",     # auto = placa de vídeo, com o processador de reserva; "cpu" = só processador
    "notificacoes": True,
    "falar": True,
    "microfone": "",                       # nome do microfone escolhido no painel; vazio = padrão do Windows
    "nome": "",                            # como o Sêneca te chama na notificação de boas-vindas; vazio = sem nome
    "cidade_clima": "",                    # cidade usada no clima do painel e em scripts/clima.ps1
    "workspace": "",                       # pasta onde ficam seus projetos; vazio = a pasta acima deste projeto
    "notion_banco": "",                    # nome do banco de tarefas no Notion; vazio = "Development Tracker"
    "notion_eu": "",                       # seu nome na conta do Notion, para o filtro "Só minhas" em Tarefas
}


# pythonw não tem console: manda prints de bibliotecas para o log.
_log_f = open(LOG, "a", encoding="utf-8", buffering=1)
if sys.stdout is None or sys.executable.lower().endswith("pythonw.exe"):
    sys.stdout = _log_f
    sys.stderr = _log_f


def log(msg: str) -> None:
    _log_f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


import logging  # noqa: E402

logging.basicConfig(stream=_log_f, level=logging.ERROR)
for nome in ("huggingface_hub", "faster_whisper"):
    logging.getLogger(nome).setLevel(logging.ERROR)

import numpy as np  # noqa: E402
import pystray  # noqa: E402
import sounddevice as sd  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from pynput import keyboard  # noqa: E402

import cerebro  # noqa: E402  (o próprio Claude, em sessão contínua)
import painel  # noqa: E402  (painel visual: http://127.0.0.1:8766)
import vozes  # noqa: E402  (perfis de voz)
import rapido  # noqa: E402  (comandos simples, sem passar pelo Claude)


def carregar_config() -> dict:
    cfg = dict(PADRAO)
    try:
        cfg.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    except FileNotFoundError:
        CONFIG.write_text(json.dumps(PADRAO, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log(f"config inválida ({e}); usando padrão")
    return cfg


# ----------------------------------------------------------------- bandeja
CORES = {
    "iniciando": (120, 120, 120),
    "pronto": (200, 164, 77),   # dourado: pronto, segure Ctrl direito
    "gravando": (220, 50, 50),    # vermelho
    "transcrevendo": (230, 160, 30),
    "pensando": (230, 160, 30),   # laranja
    "falando": (150, 80, 200),    # roxo
    "erro": (90, 90, 90),
}
DICAS = {
    "iniciando": "carregando…",
    "pronto": "segure Ctrl direito para falar",
    "gravando": "ouvindo você",
    "transcrevendo": "entendendo",
    "pensando": "pensando",
    "falando": "falando",
    "erro": "erro (veja o log)",
}


def _imagem(cor):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    hexa = [(32 + 29 * math.cos(math.radians(a)), 32 + 29 * math.sin(math.radians(a)))
            for a in range(-90, 270, 60)]
    d.polygon(hexa, fill=(8, 7, 6, 255), outline=cor + (255,), width=5)      # selo preto, borda na cor do estado
    try:
        d.text((32, 34), "S", fill=cor + (255,), font_size=34, anchor="mm")
    except Exception:
        pass
    return img


# ----------------------------------------------------------------- voz (a mesma do Sêneca)
def _sapi(texto: str):
    """Reserva offline: voz nativa do Windows."""
    script = (
        "Add-Type -AssemblyName System.Speech; $v = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$p = $v.GetInstalledVoices() | ? { $_.VoiceInfo.Culture.Name -eq 'pt-BR' } | select -First 1; "
        "if ($p) { $v.SelectVoice($p.VoiceInfo.Name) }; $v.Speak([Console]::In.ReadToEnd())"
    )
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], input=texto, text=True,
                   encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)


class Falador:
    """Sintetiza frase a frase numa thread e toca em outra; pode ser interrompido."""

    def __init__(self, perfil: dict):
        self.perfil = perfil
        self.frases: queue.Queue = queue.Queue()
        self.audios: queue.Queue = queue.Queue()
        self.geracao = 0
        self.ocupado = threading.Event()
        self._pendentes = 0
        self._lock = threading.Lock()
        threading.Thread(target=self._sintetizar, daemon=True).start()
        threading.Thread(target=self._tocar, daemon=True).start()

    def carregar(self):
        try:
            vozes.sintetizar(self.perfil, "Olá.")   # testa a voz e deixa ela pronta
        except Exception as e:
            log(f"voz neural indisponível ({e}); usando a voz do Windows")

    def falar(self, texto: str):
        for frase in dividir_frases(limpar_para_fala(texto)):
            with self._lock:
                self._pendentes += 1
            self.ocupado.set()
            self.frases.put((self.geracao, frase))

    def interromper(self):
        self.geracao += 1
        for q in (self.frases, self.audios):
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break
        with self._lock:
            self._pendentes = 0
        try:
            sd.stop()
        except Exception:
            pass
        self.ocupado.clear()

    def _terminou_uma(self):
        with self._lock:
            self._pendentes = max(0, self._pendentes - 1)
            if self._pendentes == 0:
                self.ocupado.clear()

    def _sintetizar(self):
        while True:
            ger, frase = self.frases.get()
            if ger != self.geracao:
                self._terminou_uma()
                continue
            try:
                item = vozes.sintetizar(self.perfil, frase)
            except Exception as e:
                log(f"voz neural falhou ({e}); usando a voz do Windows")
                item = frase                      # texto puro = toca via SAPI
            if ger != self.geracao:
                self._terminou_uma()
                continue
            self.audios.put((ger, item))

    def _tocar(self):
        while True:
            ger, item = self.audios.get()
            if ger == self.geracao:
                try:
                    if isinstance(item, str):
                        _sapi(item)
                    else:
                        audio, taxa = item
                        sd.play(audio, taxa)
                        sd.wait()
                except Exception as e:
                    log(f"erro ao tocar: {e}")
            self._terminou_uma()


def limpar_para_fala(t: str) -> str:
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"https?://\S+", "o link", t)
    t = re.sub(r"[*_#`>|]+", "", t)
    t = re.sub(r"^\s*[-•]\s+", "", t, flags=re.M)
    return re.sub(r"\s+", " ", t).strip()


def dividir_frases(t: str) -> list[str]:
    partes = re.split(r"(?<=[.!?…;:])\s+", t)
    frases, atual = [], ""
    for p in partes:
        atual = f"{atual} {p}".strip()
        if len(atual) >= 25:
            frases.append(atual)
            atual = ""
    if atual:
        frases.append(atual)
    return frases


# ----------------------------------------------------------------- app
class Seneca:
    def __init__(self):
        self.cfg = carregar_config()
        self.estado = "iniciando"
        self.gravando = False
        self.ocupado = False
        self.blocos: list[np.ndarray] = []
        self.cerebro = cerebro.Cerebro(log)
        painel.CEREBRO_OK = self.cerebro.vivo
        self.whisper = None
        self.falador = Falador(vozes.atual(self.cfg))
        self.tecla = getattr(keyboard.Key, self.cfg["atalho"], keyboard.Key.ctrl_r)
        self.pedido_atual = ""
        self.mic_nome = ""
        self.mic_nivel = 0.0                  # maior pico desde a última leitura do painel
        self.painel = painel.Painel(
            lambda: {"estado": self.estado, "pedido_atual": self.pedido_atual, "ocupado": self.ocupado,
                     "falar": self.cfg["falar"], "notificacoes": self.cfg["notificacoes"],
                     "mic_atual": self.mic_nome, "mic_escolhido": self.cfg["microfone"], "mic_nivel": self._ler_nivel(),
                     "contexto": self.cerebro.turnos, "sessao": self.cerebro.sessao},
            acoes={"perguntar": self.perguntar_texto, "nova_conversa": self._nova_conversa,
                   "config": self.definir_config, "reiniciar": self.cerebro.reiniciar, "abrir_sessao": self._abrir_conversa,
                   "definir_voz": self.definir_voz, "ouvir_amostra": self.ouvir_amostra,
                   "microfones": self.listar_microfones, "definir_microfone": self.definir_microfone,
                   "reiniciar_bandeja": self.reiniciar_bandeja},
        )

        menu = pystray.Menu(
            pystray.MenuItem(lambda _: f"Sêneca — {DICAS.get(self.estado, self.estado)}", None,
                             enabled=False),
            pystray.MenuItem("Abrir Centro de Comando", lambda: painel.abrir_janela(), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Responder em voz", self._alternar("falar"),
                             checked=lambda _: self.cfg["falar"]),
            pystray.MenuItem("Mostrar notificações", self._alternar("notificacoes"),
                             checked=lambda _: self.cfg["notificacoes"]),
            pystray.MenuItem("Nova conversa", self._nova_conversa),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Abrir conversa no Claude", self._abrir_conversa),
            pystray.MenuItem("Abrir log", lambda: os.startfile(LOG)),
            pystray.MenuItem("Sair", self._sair),
        )
        self.icone = pystray.Icon("seneca", _imagem(CORES["iniciando"]), "Sêneca — carregando…", menu)

    # ---------- bandeja
    def mudar(self, estado: str):
        self.estado = estado
        try:
            self.icone.icon = _imagem(CORES.get(estado, CORES["erro"]))
            self.icone.title = f"Sêneca — {DICAS.get(estado, estado)}"
            self.icone.update_menu()
        except Exception:
            pass

    def notificar(self, texto: str, titulo: str = "Sêneca"):
        if not self.cfg["notificacoes"]:
            return
        try:
            self.icone.remove_notification()
            self.icone.notify(texto[:250], titulo[:63])   # o Windows recusa título > 64
        except Exception as e:
            log(f"notificação falhou: {e}")

    def _alternar(self, chave):
        def f():
            self.cfg[chave] = not self.cfg[chave]
            if chave == "falar" and not self.cfg["falar"]:
                self.falador.interromper()
            try:
                CONFIG.write_text(json.dumps(self.cfg, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
        return f

    def _nova_conversa(self):
        self.cerebro.nova_conversa()
        self.notificar("Conversa nova. Pode falar.")

    # ---------- ações pedidas pelo Centro de Comando
    def definir_config(self, chave: str, valor: bool) -> str:
        if chave not in ("falar", "notificacoes"):
            return "opção inválida"
        if self.cfg[chave] != valor:
            self._alternar(chave)()
        return "ok"

    def ouvir_amostra(self, voz: str) -> str:
        """Toca uma frase de teste com o perfil indicado, sem mudar a voz em uso."""
        perfil = vozes.obter(voz)
        if not perfil:
            return "voz inv\u00e1lida"
        try:
            audio, taxa = vozes.sintetizar(perfil, vozes.AMOSTRA)
        except Exception as e:
            log(f"amostra de voz falhou ({voz}): {e}")
            return "N\u00e3o consegui gerar essa voz agora. O motivo ficou registrado em app\\log.txt."
        self.falador.interromper()
        sd.play(audio, taxa)
        return "ok"

    def definir_voz(self, voz: str) -> str:
        perfil = vozes.obter(voz)
        if not perfil:
            return "voz inv\u00e1lida"
        self.cfg["perfil_voz"] = voz
        self.falador.perfil = perfil
        try:
            CONFIG.write_text(json.dumps(self.cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            return f"n\u00e3o consegui salvar: {e}"
        return "ok"

    def reiniciar_bandeja(self):
        """Religa com o c\u00f3digo atualizado; a janela do painel se recarrega sozinha."""
        log("religando a bandeja")
        subprocess.Popen([str(Path(sys.executable).with_name("pythonw.exe")), str(APP / "bandeja.py"), "--reiniciando"],
                         cwd=str(APP.parent), creationflags=0x00000008 | 0x00000200)
        threading.Timer(0.3, self._sair).start()

    def perguntar_texto(self, texto: str) -> bool:
        """Pedido digitado no Centro de Comando (responde por escrito e na notificação)."""
        texto = (texto or "").strip()
        if not texto or self.ocupado or self.gravando or self.estado in ("iniciando", "erro"):
            return False
        self.ocupado = True
        threading.Thread(target=self._processar_texto, args=(texto,), daemon=True).start()
        return True

    def _processar_texto(self, texto: str):
        id_pedido = f"{int(time.time() * 1000):x}"
        try:
            painel.registrar_historico({"id": id_pedido, "tipo": "pedido", "texto": texto, "origem": "texto"})
            self.pedido_atual = texto
            self.mudar("pensando")
            log(f"você (digitado): {texto!r}")
            resposta = self.perguntar(texto, por_voz=False)
            painel.registrar_historico({"id": id_pedido, "tipo": "resposta", "texto": resposta})
            log(f"sêneca: {resposta!r}")
            self.notificar(resposta, f"Você: {texto[:50]}")
        except Exception as e:
            log("erro (texto): " + traceback.format_exc())
            painel.registrar_historico({"id": id_pedido, "tipo": "erro", "texto": f"Deu um problema: {e}"})
        finally:
            self.ocupado = False
            self.pedido_atual = ""
            if not self.gravando:
                self.mudar("pronto")

    def _abrir_conversa(self):
        painel.abrir_no_claude(self.cerebro.sessao, esperar=0)

    def _sair(self):
        log("saindo")
        self.falador.interromper()
        self.cerebro.parar()
        self.icone.stop()
        os._exit(0)

    # ---------- o pedido
    def perguntar(self, texto: str, por_voz: bool = True) -> str:
        rapida = rapido.tentar(texto)            # abrir app/pesquisar: na hora, sem esperar o modelo
        if rapida:
            log("caminho r\u00e1pido")
            return rapida
        return self.cerebro.perguntar(f"(Por voz) {texto}" if por_voz else texto)

    # ---------- microfone
    def _callback(self, indata, frames, t, status):
        self.mic_nivel = max(self.mic_nivel, float(np.abs(indata).max()))
        if self.gravando:
            self.blocos.append(indata[:, 0].copy())

    def ao_pressionar(self, tecla):
        if tecla != self.tecla or self.gravando:
            return
        if self.estado in ("iniciando", "erro"):
            return
        self.falador.interromper()          # Ctrl durante a fala = cala a boca
        if self.ocupado:
            return
        self.blocos = []
        self.gravando = True
        self.mudar("gravando")

    def ao_soltar(self, tecla):
        if tecla != self.tecla or not self.gravando:
            return
        self._parar_gravacao()

    def _parar_gravacao(self):
        self.gravando = False
        audio = np.concatenate(self.blocos) if self.blocos else np.zeros(0, dtype="float32")
        self.blocos = []
        if len(audio) < 16000 * 0.4:
            self.mudar("pronto")
            return
        self.ocupado = True
        self.mudar("pensando")
        threading.Thread(target=self._processar, args=(audio,), daemon=True).start()

    def _processar(self, audio: np.ndarray):
        try:
            pico = float(np.max(np.abs(audio))) if len(audio) else 0.0
            if pico < 0.003:
                self.notificar("Não ouvi nada. Segure o Ctrl direito enquanto fala.")
                return
            audio = (audio / pico * 0.9).astype("float32")   # microfone baixo: normaliza
            self.mudar("transcrevendo")
            t_w = time.time()
            texto = self._transcrever(audio)
            log(f"você ({time.time() - t_w:.1f}s para transcrever): {texto!r}")
            if not texto:
                self.notificar("Não entendi. Tente de novo.")
                return
            id_pedido = f"{int(time.time() * 1000):x}"
            painel.registrar_historico({"id": id_pedido, "tipo": "pedido", "texto": texto})
            self.pedido_atual = texto
            self.mudar("pensando")
            t0 = time.time()
            try:
                resposta = self.perguntar(texto)
            except Exception as e:
                painel.registrar_historico({"id": id_pedido, "tipo": "erro", "texto": f"Deu um problema: {e}"})
                raise
            painel.registrar_historico({"id": id_pedido, "tipo": "resposta", "texto": resposta})
            log(f"sêneca ({time.time() - t0:.1f}s): {resposta!r}")
            self.notificar(resposta, f"Você: {texto[:60]}")
            if self.cfg["falar"] and resposta:
                self.mudar("falando")
                self.falador.falar(resposta)
                self.ocupado = False
                time.sleep(0.2)
                while self.falador.ocupado.is_set() and not self.gravando:
                    time.sleep(0.1)
        except Exception as e:
            log("erro: " + traceback.format_exc())
            self.notificar(f"Deu um problema: {e}")
        finally:
            self.ocupado = False
            self.pedido_atual = ""
            if not self.gravando:
                self.mudar("pronto")

    # ---------- tarefas delegadas: abre o painel quando o Claude começa uma
    def _vigiar_delegadas(self):
        def ler():
            try:
                return {d["nome"]: d for d in painel.delegadas()}
            except Exception:
                return {}

        vistas = ler()
        while True:
            time.sleep(2)
            atuais = ler()
            for nome, d in atuais.items():
                antes = vistas.get(nome)
                if antes is None and d["rodando"]:
                    log(f"delegada começou: {nome} (sessão {d.get('sessao') or '-'})")
                    if d.get("sessao"):
                        # não importa agora: importada, a sessão vira uma cópia parada e sai do "ao vivo" do app
                        self.notificar(f"Acompanhe ao vivo na barra lateral do Claude: Sêneca · {d['titulo']}",
                                       "Tarefa começou")
                        painel.abrir_lista_claude()
                    else:
                        self.notificar(f"O Claude começou: {d['titulo']}. Abri o painel.", "Tarefa delegada")
                        if not self.painel.aberto_recentemente():
                            painel.abrir_janela(f"d={nome}")
                elif antes is not None and antes["rodando"] and not d["rodando"]:
                    self.notificar(f"{d['titulo']}: {d['status']}", "Tarefa")
                    if self.cfg["falar"] and not self.gravando:
                        fim = "foi concluída" if d["status"].startswith("conclu") else "não terminou bem"
                        self.falador.falar(f"A tarefa {d['titulo']} {fim}.")
            vistas = atuais

    # ---------- transcrição (placa de vídeo, com o processador de reserva)
    def _modelo_whisper(self, dispositivo: str):
        from faster_whisper import WhisperModel

        tipo = "float16" if dispositivo == "cuda" else "int8"
        return WhisperModel(self.cfg["modelo_transcricao"], device=dispositivo, compute_type=tipo)

    @staticmethod
    def _rodar_whisper(modelo, audio: np.ndarray) -> str:
        segs, _ = modelo.transcribe(audio, language="pt", beam_size=5, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segs).strip()

    def _carregar_whisper(self):
        self.whisper_cpu = None
        if self.cfg.get("dispositivo_transcricao", "auto") != "cpu":
            try:
                t0 = time.time()
                modelo = self._modelo_whisper("cuda")
                self._rodar_whisper(modelo, np.zeros(16000 * 2, dtype="float32"))   # aquece: a 1ª vez é lenta
                self.whisper = modelo
                log(f"transcrição na placa de vídeo (pronta em {time.time() - t0:.1f}s)")
                return
            except Exception as e:
                log(f"placa de vídeo indisponível ({e}); usando o processador")
        self.whisper = self.whisper_cpu = self._modelo_whisper("cpu")

    def _transcrever(self, audio: np.ndarray) -> str:
        try:
            return self._rodar_whisper(self.whisper, audio)
        except Exception as e:
            if self.whisper is self.whisper_cpu:
                raise
            log(f"transcrição na placa falhou ({e}); usando o processador nesta fala")
            if self.whisper_cpu is None:
                self.whisper_cpu = self._modelo_whisper("cpu")
            return self._rodar_whisper(self.whisper_cpu, audio)

    # ---------- microfone: o escolhido; senão o padrão do Windows; senão o primeiro que abrir
    @staticmethod
    def _entradas_microfone() -> list[tuple[int, str]]:
        """Headset Bluetooth vai por último: com o microfone aberto, o som do fone piora."""
        entradas = [(i, d["name"]) for i, d in enumerate(sd.query_devices())
                    if d["hostapi"] == sd.default.hostapi and d["max_input_channels"] > 0
                    and not re.search("mapeador|mapper", d["name"], re.I)]
        return sorted(entradas, key=lambda e: bool(re.search("headset|hands-free", e[1], re.I)))

    def _ligar_microfone(self, dispositivo):
        stream = sd.InputStream(device=dispositivo, samplerate=16000, channels=1, dtype="float32",
                                callback=self._callback)
        stream.start()
        return stream

    def _abrir_microfone(self, escolhido: str = ""):
        """-> (stream já ligado, nome do microfone em uso, aviso para o usuário)."""
        entradas = self._entradas_microfone()
        if escolhido:
            indice = next((i for i, n in entradas if n == escolhido), None)
            try:
                if indice is not None:
                    return self._ligar_microfone(indice), escolhido, ""
            except sd.PortAudioError as e:
                log(f"microfone escolhido falhou ({e})")
        try:
            padrao = sd.query_devices(kind="input")["name"]
            aviso = f" O microfone escolhido não abriu; estou usando {padrao}." if escolhido else ""
            return self._ligar_microfone(None), padrao, aviso
        except (sd.PortAudioError, ValueError) as e:
            log(f"microfone padrão falhou ({e}); procurando outro")
        ultimo_erro = RuntimeError("nenhum microfone encontrado")
        for indice, nome in entradas:
            try:
                stream = self._ligar_microfone(indice)
            except sd.PortAudioError as e:
                ultimo_erro = e
                continue
            log(f"usando o microfone: {nome}")
            return stream, nome, f" O microfone padrão falhou; estou usando {nome}."
        raise ultimo_erro

    def listar_microfones(self) -> dict:
        return {"atual": self.mic_nome, "escolhido": self.cfg["microfone"],
                "lista": sorted(n for _, n in self._entradas_microfone())}

    def definir_microfone(self, nome: str) -> str:
        """Liga o novo antes de soltar o antigo: se o novo falhar, nada muda. Nome vazio = automático."""
        if self.gravando or self.ocupado or not getattr(self, "stream", None):
            return "O Sêneca está ocupado agora. Tente em seguida."
        try:
            if nome:
                indice = next((i for i, n in self._entradas_microfone() if n == nome), None)
                if indice is None:
                    return "Esse microfone não está disponível."
                novo, atual = self._ligar_microfone(indice), nome
            else:
                novo, atual, _ = self._abrir_microfone()
        except Exception as e:
            log(f"troca de microfone falhou ({e})")
            return f"Não consegui abrir esse microfone. Continuo com {self.mic_nome}."
        antigo, self.stream = self.stream, novo
        antigo.stop()
        antigo.close()
        self.mic_nome = atual
        self.cfg["microfone"] = nome
        log(f"microfone trocado: {atual}")
        try:
            CONFIG.write_text(json.dumps(self.cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            return f"Troquei, mas não consegui salvar: {e}"
        return "ok"

    def _ler_nivel(self) -> float:
        nivel, self.mic_nivel = self.mic_nivel, 0.0
        return round(nivel, 3)

    # ---------- início
    def _carregar(self):
        try:
            if not self.painel.iniciar():
                log("painel: porta 8766 ocupada")
            rapido.iniciar()
            threading.Thread(target=self._vigiar_delegadas, daemon=True).start()
            threading.Thread(target=self.cerebro.iniciar, daemon=True).start()
            self._carregar_whisper()
            self.falador.carregar()
            self.stream, self.mic_nome, aviso_mic = self._abrir_microfone(self.cfg["microfone"])
            keyboard.Listener(on_press=self.ao_pressionar, on_release=self.ao_soltar,
                              daemon=True).start()
            self.mudar("pronto")
            log("pronto")
            nome = self.cfg.get("nome", "").strip()
            self.notificar(f"Pronto{', ' + nome if nome else ''}. Segure o Ctrl direito e fale.{aviso_mic}")
        except Exception as e:
            log("erro ao iniciar: " + traceback.format_exc())
            self.mudar("erro")
            self.notificar(f"Não consegui iniciar: {e}")

    def _garantir_atalhos(self):
        """Atalho "Sêneca" na área de trabalho e no menu Iniciar (abre o programa)."""
        try:
            pastas = [Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"]
            buf = ctypes.create_unicode_buffer(260)       # área de trabalho (pode estar no OneDrive)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:
                pastas.append(Path(buf.value))
            faltando = [p / "Sêneca.lnk" for p in pastas if not (p / "Sêneca.lnk").exists()]
            if not faltando:
                return
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            linhas = ["$s = New-Object -ComObject WScript.Shell"]
            for lnk in faltando:
                linhas += [f"$l = $s.CreateShortcut('{lnk}')", f"$l.TargetPath = '{pythonw}'",
                           f"$l.Arguments = '\"{APP / 'seneca_app.pyw'}\"'", f"$l.WorkingDirectory = '{APP}'",
                           f"$l.IconLocation = '{APP / 'seneca.ico'},0'",
                           "$l.Description = 'Sêneca — Centro de Comando'", "$l.Save()"]
            subprocess.run(["powershell.exe", "-NoProfile", "-Command", "; ".join(linhas)],
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
            log(f"atalhos criados: {[str(x) for x in faltando]}")
        except Exception as e:
            log(f"atalhos: {e}")

    def rodar(self):
        threading.Thread(target=self._garantir_atalhos, daemon=True).start()
        threading.Thread(target=self._carregar, daemon=True).start()
        self.icone.run()


def main():
    k = ctypes.windll.kernel32
    tentativas = 40 if "--reiniciando" in sys.argv else 1      # na religada, espera o processo antigo sair
    for i in range(tentativas):
        mutex = k.CreateMutexW(None, False, "Local\\SenecaBandeja")
        if k.GetLastError() != 183:
            break
        k.CloseHandle(mutex)
        if i == tentativas - 1:
            return                                             # já está rodando
        time.sleep(0.5)
    log("=== iniciando Sêneca ===")
    Seneca().rodar()
    del mutex


if __name__ == "__main__":
    main()
