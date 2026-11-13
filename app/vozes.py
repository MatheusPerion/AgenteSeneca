"""As vozes do Sêneca: perfis prontos (voz + velocidade + tom), online (edge-tts, ElevenLabs) ou locais (Piper)."""
from __future__ import annotations

import asyncio
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

APP = Path(__file__).resolve().parent
CONFIG = APP / "config.json"
MODELOS = APP / "vozes"
AMOSTRA = "A vida, se bem empregada, é longa o bastante. Não temos pouco tempo; é que perdemos muito."
SABIAS, LOCAIS, OUTRAS, PREMIUM = "Com ar de sabedoria", "Locais, sem internet", "Outras", "ElevenLabs"
ELEVEN_ARQ = APP.parent / "config" / "elevenlabs.json"    # a chave fica aqui; é lida a cada fala
ERROS = APP / "dados" / "cerebro-erros.log"
PAUSA_ELEVEN = 600                                        # depois de uma falha, 10 min só com a voz reserva
_eleven_volta = 0.0


def _edge(id, nome, desc, voz, velocidade, tom, grupo=SABIAS):
    return {"id": id, "nome": nome, "descricao": desc, "motor": "edge", "voz": voz, "velocidade": velocidade, "tom": tom, "grupo": grupo}


def _piper(id, nome, desc, modelo, lento, grave):
    # lento: alonga a fala; grave: toca um pouco mais devagar, o que engrossa a voz
    return {"id": id, "nome": nome, "descricao": desc, "motor": "piper", "modelo": modelo, "lento": lento, "grave": grave, "grupo": LOCAIS}


def _eleven(id, nome, desc, voz, modelo="eleven_multilingual_v2"):
    return {"id": id, "nome": nome, "descricao": desc, "motor": "eleven", "voz": voz, "modelo": modelo, "grupo": PREMIUM}


PERFIS = [
    _eleven("brian", "Brian", "Grave, ressonante e acolhedora. Consome créditos da ElevenLabs.", "nPczCjzI2devNBz1zQrb"),
    _edge("velho-sabio", "Velho sábio", "A voz atual, mais lenta e bem mais grave. Fala de ancião.", "pt-BR-AntonioNeural", "-14%", "-24Hz"),
    _edge("mestre-sereno", "Mestre sereno", "Antonio pausado e levemente grave. Calmo, sem exagero.", "pt-BR-AntonioNeural", "-9%", "-12Hz"),
    _edge("filosofo-lusitano", "Filósofo lusitano", "Português de Portugal, pausado e solene.", "pt-PT-DuarteNeural", "-10%", "-14Hz"),
    _edge("orador-romano", "Orador romano", "Sotaque italiano, grave. O mais próximo de Roma.", "it-IT-GiuseppeMultilingualNeural", "-10%", "-14Hz"),
    _edge("preceptor", "Preceptor", "Voz calorosa com leve sotaque estrangeiro, ritmo de quem ensina.", "en-US-AndrewMultilingualNeural", "-10%", "-12Hz"),
    _edge("estoico-severo", "Estoico severo", "Sotaque alemão, firme e grave.", "de-DE-FlorianMultilingualNeural", "-8%", "-14Hz"),
    _piper("faber", "Faber", "Voz brasileira grave, tom de leitura.", "pt_BR-faber-medium", 1.18, 0.93),
    _piper("cadu", "Cadu", "Brasileira e serena.", "pt_BR-cadu-medium", 1.12, 0.92),
    _piper("jeff", "Jeff", "Brasileira e clara, com pausas longas.", "pt_BR-jeff-medium", 1.10, 0.92),
    _piper("edresson", "Edresson", "Brasileira mais simples, muito rápida de gerar.", "pt_BR-edresson-low", 1.10, 0.93),
    _edge("classico", "Sêneca clássico", "A voz que ele usa desde o começo.", "pt-BR-AntonioNeural", "+0%", "-4Hz", OUTRAS),
    _edge("francisca", "Francisca", "Feminina, brasileira.", "pt-BR-FranciscaNeural", "-5%", "-4Hz", OUTRAS),
    _edge("raquel", "Raquel", "Feminina, de Portugal.", "pt-PT-RaquelNeural", "-5%", "-4Hz", OUTRAS),
]
_POR_ID = {p["id"]: p for p in PERFIS}
_carregadas: dict = {}
_lock = threading.Lock()


def _config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def obter(id: str) -> dict | None:
    return _POR_ID.get(id)


def atual(cfg: dict | None = None) -> dict:
    cfg = _config() if cfg is None else cfg
    return obter(cfg.get("perfil_voz", "")) or obter("classico")


def _chave_eleven() -> str:
    try:
        return json.loads(ELEVEN_ARQ.read_text(encoding="utf-8")).get("api_key", "").strip()
    except Exception:
        return ""


def _disponivel(p: dict) -> bool:
    if p["motor"] == "eleven":
        return bool(_chave_eleven())
    return p["motor"] != "piper" or (MODELOS / f"{p['modelo']}.onnx").exists()


def perfis() -> dict:
    em_uso = atual()["id"]
    return {"atual": em_uso, "lista": [{"id": p["id"], "nome": p["nome"], "descricao": p["descricao"], "grupo": p["grupo"],
                                        "local": p["motor"] == "piper", "disponivel": _disponivel(p)} for p in PERFIS]}


def _aparar(audio: np.ndarray, taxa: int):
    fala = np.nonzero(np.abs(audio) > 300)[0]          # corta o silêncio do fim
    if len(fala):
        audio = audio[: min(len(audio), fala[-1] + int(0.12 * taxa))]
    return audio, taxa


def _decodificar_mp3(mp3: bytes):
    import miniaudio

    d = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1)
    return _aparar(np.frombuffer(d.samples, dtype=np.int16), d.sample_rate)


def _sintetizar_edge(p: dict, texto: str):
    import edge_tts

    async def baixar():
        buf = bytearray()
        async for c in edge_tts.Communicate(texto, p["voz"], rate=p["velocidade"], pitch=p["tom"]).stream():
            if c["type"] == "audio":
                buf += c["data"]
        return bytes(buf)

    return _decodificar_mp3(asyncio.run(baixar()))


def _sintetizar_eleven(p: dict, texto: str, chave: str):
    pedido = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{p['voz']}?output_format=pcm_24000",     # áudio cru: não precisa decodificar
        data=json.dumps({"text": texto, "model_id": p["modelo"]}).encode("utf-8"),
        headers={"xi-api-key": chave, "Content-Type": "application/json"})
    with urllib.request.urlopen(pedido, timeout=20) as r:
        return _aparar(np.frombuffer(r.read(), dtype=np.int16), 24000)


def _reserva() -> dict:
    p = obter(_config().get("perfil_reserva", ""))
    return p if p and p["motor"] != "eleven" else obter("classico")


def _falha_eleven(e: Exception) -> None:
    global _eleven_volta
    _eleven_volta = time.time() + PAUSA_ELEVEN
    detalhe = e.read().decode("utf-8", "replace")[:200] if isinstance(e, urllib.error.HTTPError) else ""
    try:
        with open(ERROS, "a", encoding="utf-8") as f:
            f.write(f"[voz] ElevenLabs falhou, usando a reserva por 10 min: {e} {detalhe}\n")
    except OSError:
        pass


def _sintetizar_piper(p: dict, texto: str):
    from piper import PiperVoice, SynthesisConfig

    with _lock:
        voz = _carregadas.get(p["modelo"])
        if voz is None:
            voz = _carregadas[p["modelo"]] = PiperVoice.load(str(MODELOS / f"{p['modelo']}.onnx"))
        partes = list(voz.synthesize(texto, syn_config=SynthesisConfig(length_scale=p["lento"])))
    audio = np.concatenate([np.frombuffer(x.audio_int16_bytes, dtype=np.int16) for x in partes])
    return _aparar(audio, int(partes[0].sample_rate * p["grave"]))


def sintetizar(p: dict, texto: str):
    """-> (áudio int16, taxa). Gera a fala com o perfil escolhido; sem chave, sem crédito ou sem rede, usa a voz reserva."""
    if p["motor"] == "eleven":
        chave = _chave_eleven()
        if chave and time.time() >= _eleven_volta:
            try:
                return _sintetizar_eleven(p, texto, chave)
            except Exception as e:
                _falha_eleven(e)
        p = _reserva()
    return (_sintetizar_piper if p["motor"] == "piper" else _sintetizar_edge)(p, texto)
