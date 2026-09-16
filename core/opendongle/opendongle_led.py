#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongle_led.py — os 3 LEDs contam o estado do dongle sem precisar de SSH
============================================================================
Roda NO DONGLE como serviço. Único motor que decide o que os LEDs físicos
(`red:power`, `green:wlan`, `blue:wan`, driver `leds-gpio`) mostram — CLI e
painel web não mexem nisso, só este serviço escreve em /sys/class/leds.

Cada LED tem um papel único (nunca dois LEDs competem pelo mesmo estado);
a ordem abaixo é a ordem de prioridade — o primeiro item que bater decide
o que aparece, os de baixo só são avaliados se os de cima não se aplicam:

  1) papel da porta USB (device/host) — decide se os LEDs têm algo pra
     mostrar. device (plugado no PC) -> tudo apagado, a tela do PC já
     mostra status. host (com periféricos, standalone) -> segue abaixo.
  2) erro/pane (role-switch sumiu, nmcli não responde, ou flag externa
     em /run/opendongle-led/error) -> vermelho pisca RÁPIDO.
  3) cliente de Wi-Fi ativo -> azul aceso fixo (com internet) ou piscando
     MODERADO (sem internet).
  4) hotspot ativo -> verde aceso fixo (com internet pra repassar) ou
     piscando MODERADO (sem internet pra repassar).
  5) nem hotspot nem cliente (rádio Wi-Fi ocioso/indefinido) -> vermelho
     aceso fixo.

Bônus: com áudio tocando, o LED que estiver aceso FIXO (azul ou verde)
passa a piscar no ritmo do áudio — nunca atropela erro nem aviso "sem
internet" (esses têm prioridade e já usam o piscar pra outra coisa).

Sem dependências obrigatórias: stdlib + opendongle_engine (modo do Wi-Fi e
internet). O bônus de áudio usa `arecord` (pacote alsa-utils) só se
disponível; sem ele, cai num piscar de frequência fixa.
"""

import glob
import os
import re
import shutil
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opendongle_engine as eng

ROLE_SW = "/sys/class/usb_role/ci_hdrc.0-role-switch/role"
LED_DIR = "/sys/class/leds"
ERROR_FLAG = "/run/opendongle-led/error"   # outros serviços podem criar esse arquivo pra forçar erro

INTERVALO_ESTADO = 3           # segundos entre reavaliações de USB/Wi-Fi/internet
AUDIO_POLL = 0.5               # segundos entre checagens de "áudio tocando"
BLINK_MODERADO = (500, 500)    # ms on/off — "em progresso / aviso"
BLINK_RAPIDO = (100, 100)      # ms on/off — erro
BLINK_AUDIO_FALLBACK = (90, 90)  # sem loopback pra medir amplitude, só um "vivo" fixo


def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception:
        return 1, "", "falha ao executar"


# --------------------------------------------------------------- LEDs
class Led:
    """Um LED em /sys/class/leds/<nome>. Só escreve no sysfs quando o
    estado pedido muda — evita reescrever à toa a cada ciclo."""

    def __init__(self, nome_sysfs):
        self.dir = os.path.join(LED_DIR, nome_sysfs)
        self._ultimo = None

    def _write(self, arquivo, valor):
        try:
            with open(os.path.join(self.dir, arquivo), "w") as f:
                f.write(str(valor))
        except OSError:
            pass

    def off(self):
        if self._ultimo == ("off",):
            return
        self._write("trigger", "none")
        self._write("brightness", 0)
        self._ultimo = ("off",)

    def on(self):
        if self._ultimo == ("on",):
            return
        self._write("trigger", "none")
        self._write("brightness", 1)
        self._ultimo = ("on",)

    def blink(self, delay_on_ms, delay_off_ms):
        estado = ("blink", delay_on_ms, delay_off_ms)
        if self._ultimo == estado:
            return
        self._write("trigger", "timer")
        self._write("delay_on", delay_on_ms)
        self._write("delay_off", delay_off_ms)
        self._ultimo = estado

    def brightness_bruto(self, valor):
        """Escreve brightness direto (0/1) pro efeito de áudio — aqui a
        frequência é alta e o valor muda sempre, não vale a pena checar
        'mudou' como nos outros modos."""
        self._write("brightness", valor)
        self._ultimo = None   # próxima chamada de on()/off()/blink() força reescrita


LED_RED = Led("red:power")
LED_GREEN = Led("green:wlan")
LED_BLUE = Led("blue:wan")


def todos_apagados():
    LED_RED.off()
    LED_GREEN.off()
    LED_BLUE.off()


# --------------------------------------------------------------- leituras de estado
def papel_usb():
    """'device', 'host' ou None se o role-switch não existir (hardware/
    driver com problema — quem chama trata como erro)."""
    try:
        with open(ROLE_SW) as f:
            return f.read().strip()
    except OSError:
        return None


def erro_pendente():
    return os.path.exists(ERROR_FLAG)


# --------------------------------------------------------------- áudio (bônus)
def audio_tocando():
    """True se existir algum substream de PLAYBACK em RUNNING em qualquer
    placa ALSA — funciona com qualquer servidor de som por cima (pulseaudio,
    pipewire ou ALSA puro), porque olha direto o estado do kernel."""
    for status in glob.glob("/proc/asound/card*/pcm*p/sub*/status"):
        try:
            with open(status) as f:
                if "RUNNING" in f.read():
                    return True
        except OSError:
            continue
    return False


def _card_loopback_captura():
    """Acha o device de captura do snd-aloop (card 'Loopback'), se o módulo
    estiver carregado — é o que dá o nível real do áudio (testado em
    dongle/context.md, seção 4). Sem ele, cai no piscar de frequência fixa."""
    rc, out, _ = _run(["cat", "/proc/asound/cards"])
    if rc != 0:
        return None
    m = re.search(r"^\s*(\d+)\s*\[Loopback", out, re.MULTILINE)
    return f"hw:{m.group(1)},1,0" if m else None


class EfeitoAudio:
    """Gerencia a thread que pisca um LED no ritmo do áudio, enquanto ele
    estiver tocando. Chame ajustar(led_alvo) a cada ciclo do laço principal:
    led_alvo=None para desligar o efeito; um Led pra ligar/realocar nele."""

    def __init__(self):
        self._thread = None
        self._parar = threading.Event()
        self._led_atual = None

    def ajustar(self, led_alvo):
        if led_alvo is self._led_atual:
            return
        self._desligar()
        if led_alvo is not None:
            self._led_atual = led_alvo
            self._parar = threading.Event()
            self._thread = threading.Thread(
                target=self._loop, args=(led_alvo, self._parar), daemon=True)
            self._thread.start()

    def _desligar(self):
        if self._thread is not None:
            self._parar.set()
            self._thread.join(timeout=2)
        self._thread = None
        self._led_atual = None

    @staticmethod
    def _loop(led, parar):
        dev = _card_loopback_captura() if shutil.which("arecord") else None
        if dev is None:
            on_ms, off_ms = BLINK_AUDIO_FALLBACK
            while not parar.is_set():
                led.brightness_bruto(1)
                parar.wait(on_ms / 1000)
                led.brightness_bruto(0)
                parar.wait(off_ms / 1000)
            return

        proc = subprocess.Popen(
            ["arecord", "-D", dev, "-f", "S16_LE", "-r", "8000", "-c", "1", "-t", "raw"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        CHUNK = 800     # ~0.05s em 8kHz/16bit mono
        LIMIAR = 1500   # amplitude mínima (de 32767) pra considerar "som alto"
        try:
            while not parar.is_set():
                buf = proc.stdout.read(CHUNK)
                if not buf:
                    break
                pico = max(
                    (abs(int.from_bytes(buf[i:i + 2], "little", signed=True))
                     for i in range(0, len(buf) - 1, 2)),
                    default=0)
                led.brightness_bruto(1 if pico > LIMIAR else 0)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()


# --------------------------------------------------------------- laço principal
def aplicar_estado(efeito_audio):
    """Aplica o estado 'grande' (USB/Wi-Fi/internet) e devolve qual LED é
    candidato a ganhar o efeito de áudio agora (None se nenhum — erro,
    device, ou um LED já piscando aviso não aceitam o efeito)."""
    papel = papel_usb()

    if erro_pendente() or papel is None:
        efeito_audio.ajustar(None)
        LED_RED.blink(*BLINK_RAPIDO)
        LED_GREEN.off()
        LED_BLUE.off()
        return None

    if papel == "device":
        efeito_audio.ajustar(None)
        todos_apagados()
        return None

    # papel == "host": segue a ordem de prioridade das outras regras
    modo = eng.modo_wifi()

    if modo == "erro":
        efeito_audio.ajustar(None)
        LED_RED.blink(*BLINK_RAPIDO)
        LED_GREEN.off()
        LED_BLUE.off()
        return None

    if modo == "wifi":
        LED_RED.off()
        LED_GREEN.off()
        if eng.tem_internet():
            LED_BLUE.on()
            return LED_BLUE
        efeito_audio.ajustar(None)
        LED_BLUE.blink(*BLINK_MODERADO)
        return None

    if modo == "hotspot":
        LED_RED.off()
        LED_BLUE.off()
        if eng.tem_internet():
            LED_GREEN.on()
            return LED_GREEN
        efeito_audio.ajustar(None)
        LED_GREEN.blink(*BLINK_MODERADO)
        return None

    # nem hotspot, nem cliente: rádio Wi-Fi ocioso/indefinido
    efeito_audio.ajustar(None)
    LED_RED.on()
    LED_GREEN.off()
    LED_BLUE.off()
    return None


def laco():
    """Laço dos LEDs. Roda como thread do opendongled (ou sozinho pelo main).
    A internet vem do cache do engine, renovado pelo laço do uplink_guard."""
    efeito_audio = EfeitoAudio()
    led_candidato = None
    proxima_avaliacao = 0.0
    while True:
        agora = time.time()
        if agora >= proxima_avaliacao:
            led_candidato = aplicar_estado(efeito_audio)
            proxima_avaliacao = agora + INTERVALO_ESTADO
        # a cada AUDIO_POLL, liga/desliga o efeito de áudio no LED
        # candidato do momento (sem repetir ping/nmcli à toa)
        efeito_audio.ajustar(led_candidato if audio_tocando() else None)
        time.sleep(AUDIO_POLL)


if __name__ == "__main__":
    # modo teste: 'python3 opendongle_led.py once' aplica o estado uma vez e sai
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        aplicar_estado(EfeitoAudio())
        print("papel_usb:", papel_usb())
        print("modo_wifi:", eng.modo_wifi())
        print("tem_internet:", eng.tem_internet())
        print("audio_tocando:", audio_tocando())
        sys.exit(0)
    if os.geteuid() != 0:
        sys.exit("Precisa rodar como root (é um serviço de sistema).")
    try:
        laco()
    except KeyboardInterrupt:
        pass
