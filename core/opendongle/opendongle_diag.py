#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongle_diag.py — diagnóstico de hardware "adormecido" do dongle
======================================================================
Roda NO DONGLE. Testa de verdade (não só "o serviço subiu") os
subsistemas de hardware que o OpenDongle desbloqueia: áudio, Bluetooth,
vídeo USB (webcam externa) e modem 4G. Usado por `sudo opendongle
diagnostico` e pelo instalador, logo depois do reboot que ativa o
usb-role-autosense.

Cada item devolve um destes três vereditos:
  ok            — testado de verdade e funcionando.
  falha         — deveria funcionar (hardware sempre presente na placa)
                  e não funcionou. Vale investigar.
  nao_testavel  — depende de algo que não está disponível agora (sem
                  câmera USB plugada, sem SIM inserido, ferramenta não
                  instalada). NÃO é uma falha do dongle.

Sem dependências obrigatórias: cada teste checa se a ferramenta que
precisa existe antes de tentar usá-la, e nunca deixa o dongle pior do
que encontrou (limpa arquivos temporários, não desliga nada que já
estava ligado).
"""

import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import tty

AT_DEV = "/dev/wwan0at0"
QMI_DEV = "/dev/wwan0qmi0"
AUDIO_TMP = "/tmp/opendongle_diag_audio.raw"


def _run(cmd, timeout=10, entrada=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, input=entrada)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", f"comando não encontrado: {cmd[0]}"


def _at(cmd, espera=3):
    """Envia um comando AT pro modem e devolve a resposta (raw, sem
    dependências: só abre o tty e lê/escreve). Nunca trava — timeout
    interno (alarm) + externo."""
    if not os.path.exists(AT_DEV):
        return ""
    def _al(*_a):
        raise TimeoutError
    anterior = signal.signal(signal.SIGALRM, _al)
    signal.alarm(int(espera) + 2)
    try:
        fd = os.open(AT_DEV, os.O_RDWR)
        tty.setraw(fd)
        try:
            time.sleep(0.2)
            try:
                os.read(fd, 4096)
            except OSError:
                pass
            os.write(fd, (cmd + "\r").encode())
            buf = b""
            fim = time.time() + espera
            while time.time() < fim:
                r = os.read(fd, 4096) if _pronto(fd, 0.15) else b""
                if r:
                    buf += r
                    if b"OK" in buf or b"ERROR" in buf:
                        break
            return buf.decode(errors="replace")
        finally:
            os.close(fd)
    except (OSError, TimeoutError):
        return ""
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, anterior)


def _pronto(fd, timeout):
    import select
    r, _, _ = select.select([fd], [], [], timeout)
    return bool(r)


# --------------------------------------------------------------- áudio
def teste_audio():
    if not (shutil.which("arecord") and shutil.which("aplay")
            and shutil.which("speaker-test")):
        return "nao_testavel", "alsa-utils não instalado"

    _run(["modprobe", "snd_aloop"])
    rc, out, _ = _run(["cat", "/proc/asound/cards"])
    m = re.search(r"^\s*(\d+)\s*\[Loopback", out or "", re.MULTILINE)
    if not m:
        return "falha", "módulo snd_aloop não carregou (sem placa Loopback)"
    card = m.group(1)
    dev_play, dev_cap = f"hw:{card},0,0", f"hw:{card},1,0"

    try:
        os.remove(AUDIO_TMP)
    except OSError:
        pass
    gravador = subprocess.Popen(
        ["arecord", "-D", dev_cap, "-f", "S16_LE", "-r", "8000", "-c", "1",
         "-d", "2", "-t", "raw", AUDIO_TMP],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.3)
    # -r 8000 tem que bater com o -r do arecord acima: o par do snd-aloop
    # trava a taxa no primeiro lado que abrir, e o speaker-test tenta
    # 48000Hz por padrão — sem isso ele falha ao abrir e grava só silêncio.
    _run(["timeout", "1.5", "speaker-test", "-D", dev_play, "-c", "1",
          "-t", "sine", "-f", "440", "-r", "8000"], timeout=3)
    try:
        gravador.wait(timeout=4)
    except subprocess.TimeoutExpired:
        gravador.kill()

    try:
        dados = open(AUDIO_TMP, "rb").read()
    except OSError:
        dados = b""
    finally:
        try:
            os.remove(AUDIO_TMP)
        except OSError:
            pass

    if len(dados) < 1000:
        return "falha", "loopback não gravou nada (pipeline ALSA quebrado)"
    pico = max(
        (abs(int.from_bytes(dados[i:i + 2], "little", signed=True))
         for i in range(0, len(dados) - 1, 2)),
        default=0)
    if pico < 500:
        return "falha", f"gravou só silêncio (pico={pico}/32767) — playback ou captura não conectam"
    return "ok", f"loopback saída→entrada confirmado (pico={pico}/32767)"


# --------------------------------------------------------------- bluetooth
def teste_bluetooth():
    if not shutil.which("hciconfig"):
        return "nao_testavel", "bluez não instalado"
    _run(["rfkill", "unblock", "bluetooth"])
    _run(["hciconfig", "hci0", "up"], timeout=8)
    rc, out, _ = _run(["hciconfig", "hci0"], timeout=5)
    if rc != 0 or "hci0" not in out:
        return "falha", "hci0 não existe (chip WCN3620/firmware não subiu)"
    if "UP RUNNING" in out:
        return "ok", "hci0 ligado (UP RUNNING)"
    return "falha", f"hci0 existe mas não subiu: {out.splitlines()[0] if out else '?'}"


# --------------------------------------------------------------- vídeo USB
def teste_video():
    rc, out, _ = _run(["modinfo", "uvcvideo"], timeout=5)
    driver_ok = rc == 0
    dispositivos = sorted(glob.glob("/dev/video*"))
    if not dispositivos:
        detalhe = ("nenhuma câmera USB conectada agora" +
                   ("" if driver_ok else " (e o driver uvcvideo nem está disponível)"))
        return "nao_testavel", detalhe
    if not shutil.which("v4l2-ctl"):
        return "nao_testavel", f"câmera em {dispositivos[0]}, mas v4l-utils não instalado"
    rc, out, err = _run(
        ["v4l2-ctl", "-d", dispositivos[0], "--stream-mmap",
         "--stream-count=1", "--stream-to=/dev/null"], timeout=10)
    if rc == 0:
        return "ok", f"capturou 1 frame de {dispositivos[0]}"
    return "falha", f"{dispositivos[0]} não capturou: {(err or out)[:100]}"


# --------------------------------------------------------------- modem 4G
def teste_modem():
    if not (os.path.exists(AT_DEV) and os.path.exists(QMI_DEV)):
        return "falha", "portas do modem não apareceram (firmware mpss não subiu)"

    resp = _at("ATI", 3)
    if "QUALCOMM" not in resp.upper() and "OK" not in resp.upper():
        return "falha", "modem não respondeu a ATI (hardware/firmware com problema)"

    sim_resp = _at("AT+CIMI", 4)
    imsi = re.search(r"\d{14,15}", sim_resp)
    if imsi:
        return "ok", f"modem responde, SIM detectado (IMSI {imsi.group()[:6]}…)"
    return "ok", "modem responde (hardware OK); sem SIM inserido — internet 4G não testável agora"


TESTES = [
    ("áudio (loopback)", teste_audio),
    ("bluetooth", teste_bluetooth),
    ("vídeo USB (webcam)", teste_video),
    ("modem 4G", teste_modem),
]


def rodar_tudo():
    resultados = []
    for nome, fn in TESTES:
        try:
            status, detalhe = fn()
        except Exception as e:
            status, detalhe = "falha", f"erro inesperado no teste: {e}"
        resultados.append({"nome": nome, "status": status, "detalhe": detalhe})
    return resultados


ICONE = {"ok": "✅", "falha": "❌", "nao_testavel": "➖"}


def imprimir_relatorio(resultados):
    for r in resultados:
        print(f"{ICONE.get(r['status'], '?')} {r['nome']}: {r['detalhe']}")
    falhas = [r for r in resultados if r["status"] == "falha"]
    if falhas:
        print(f"\n{len(falhas)} item(ns) com falha — tentar resolver manualmente.")
    else:
        print("\nNenhuma falha (itens ➖ só precisam do periférico conectado pra testar).")
    return len(falhas) == 0


if __name__ == "__main__":
    resultados = rodar_tudo()
    if "--json" in sys.argv:
        print(json.dumps(resultados, ensure_ascii=False))
        sys.exit(0 if all(r["status"] != "falha" for r in resultados) else 1)
    ok = imprimir_relatorio(resultados)
    sys.exit(0 if ok else 1)
