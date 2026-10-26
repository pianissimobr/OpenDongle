#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongle_relogio.py — a hora do dongle é confiável?
======================================================
O MSM8916 não tem relógio com bateria. Ao ligar, o timesyncd retoma do último
instante salvo (o "piso"), e sem internet a hora fica atrasada pelo tempo que o
aparelho passou desligado. Logs, certificados (TLS falha com a data errada) e
qualquer coisa agendada dependem de a hora estar certa.

Este laço (thread do opendongled) decide e publica em /run/opendongle/relogio.json:

    {"confiavel": bool, "fonte": "...", "desde": epoch, "ajuste_s": n}

O arquivo fica em tmpfs de propósito: a cada boot a hora volta a ser "não
confiável" até alguma fonte confirmar. Quem precisar de hora certa (antes de
agendar algo, por exemplo) lê esse arquivo.

Fontes, na ordem de preferência:
  1. NTP        — o timesyncd sincronizou neste boot
  2. navegador  — alguém abriu o painel (opendongle_sistema.hora_do_navegador)
  3. rede celular — hora do modem pelo QMI (DMS Get Time), se houver SIM
  4. HTTP       — cabeçalho Date de dois servidores diferentes que concordam
Nenhuma fonte pode levar o relógio para antes do piso.
"""

import json
import os
import re
import subprocess
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

ESTADO = "/run/opendongle/relogio.json"
MARCA_NAVEGADOR = "/run/opendongle/relogio-navegador"   # gravada por hora_do_navegador
TIMESYNC_OK = "/run/systemd/timesync/synchronized"
PISO = "/var/lib/systemd/timesync/clock"
QMI_DEV = "/dev/wwan0qmi0"
HOSTS_HTTP = ("http://connectivitycheck.gstatic.com/generate_204",
              "http://detectportal.firefox.com/success.txt")
CONCORDANCIA_S = 120           # duas fontes HTTP precisam bater dentro disso
AJUSTE_MIN_S = 60              # diferença menor não justifica mexer no relógio
INTERVALO_INICIO_S = 20        # enquanto não confia, tenta com frequência
INTERVALO_OK_S = 600           # depois, só confere se o NTP não sumiu
_GPS_EPOCH = datetime(1980, 1, 6, tzinfo=timezone.utc)


def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 1, "", str(e)


def _piso():
    try:
        return os.path.getmtime(PISO)
    except OSError:
        return datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()


def _publicar(confiavel, fonte, ajuste_s=0):
    os.makedirs(os.path.dirname(ESTADO), exist_ok=True)
    tmp = ESTADO + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"confiavel": confiavel, "fonte": fonte, "desde": int(time.time()),
                   "ajuste_s": int(ajuste_s)}, f)
    os.replace(tmp, ESTADO)


def ler():
    try:
        with open(ESTADO) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"confiavel": False, "fonte": "desconhecida"}


def _acertar(alvo):
    """Ajusta o relógio para `alvo` (epoch). Devolve o ajuste em segundos, ou None."""
    if alvo < _piso():
        return None
    diferenca = alvo - time.time()
    if abs(diferenca) < AJUSTE_MIN_S:
        return 0
    rc, _, _ = _run(["date", "-u", "-s", f"@{alvo:.0f}"])
    if rc != 0:
        return None
    try:
        os.utime(PISO)            # o próximo boot já parte desta hora
    except OSError:
        pass
    return diferenca


# ------------------------------------------------------------------ fontes --
def hora_modem():
    """DMS Get Time: contagem em unidades de 1,25 ms desde a época GPS.

    Verificar no campo: alguns firmwares devolvem a hora do próprio aparelho
    (fonte 'device') em vez da rede — por isso a sanidade contra o piso.
    """
    if not os.path.exists(QMI_DEV):
        return None
    rc, out, _ = _run(["qmicli", "-p", "-d", QMI_DEV, "--dms-get-time"])
    if rc != 0:
        return None
    m = re.search(r"Time count:\s*'?(\d+)", out)
    if not m:
        return None
    quando = _GPS_EPOCH + timedelta(milliseconds=int(m.group(1)) * 1.25)
    epoch = quando.timestamp()
    return epoch if epoch >= _piso() else None


def hora_http():
    horas = []
    for url in HOSTS_HTTP:
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=8) as r:
                data = r.headers.get("Date")
            if data:
                horas.append(parsedate_to_datetime(data).timestamp())
        except (OSError, ValueError, TypeError):
            continue
    if len(horas) == 2 and abs(horas[0] - horas[1]) <= CONCORDANCIA_S:
        return sum(horas) / 2
    return None


# ------------------------------------------------------------------- laço --
def avaliar():
    """Uma rodada: devolve (confiavel, fonte, ajuste_s) e publica."""
    if os.path.exists(TIMESYNC_OK):
        estado = (True, "ntp", 0)
    elif os.path.exists(MARCA_NAVEGADOR):
        estado = (True, "navegador", 0)
    else:
        estado = (False, "aguardando internet ou navegador", 0)
        for nome, fonte in (("rede celular", hora_modem), ("http", hora_http)):
            alvo = fonte()
            if alvo is None:
                continue
            ajuste = _acertar(alvo)
            if ajuste is not None:
                estado = (True, nome, ajuste)
                break
    anterior = ler()
    if anterior.get("confiavel") and not estado[0]:
        # já confiou neste boot: o relógio não "desacerta" sozinho
        return anterior.get("confiavel"), anterior.get("fonte"), 0
    if (anterior.get("confiavel"), anterior.get("fonte")) != estado[:2] or estado[2]:
        _publicar(*estado)
    return estado


def laco():
    while True:
        confiavel, _, _ = avaliar()
        time.sleep(INTERVALO_OK_S if confiavel else INTERVALO_INICIO_S)


if __name__ == "__main__":
    print(json.dumps(dict(zip(("confiavel", "fonte", "ajuste_s"), avaliar())),
                     ensure_ascii=False))
