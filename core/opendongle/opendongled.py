#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongled.py — todos os serviços do OpenDongle num processo Python só
=========================================================================
Antes eram 4 serviços (painel web, uplink guard, LEDs, descoberta), cada
um com seu próprio interpretador Python (~29 MB somados, medido em PSS).
Aqui eles viram threads do mesmo processo e compartilham o cache de
"tem internet?" do engine — o laço do uplink renova, LED e painel só leem.

Cada thread tem um supervisor: se o laço morrer por exceção, ele registra
no journal e reinicia só aquela parte (o que antes o Restart= de cada
unit do systemd fazia).
"""

import os
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opendongle_discovery
import opendongle_led
import opendongle_web
import uplink_guard

ESPERA_REINICIO = 5   # segundos antes de reiniciar um laço que morreu


def _supervisionar(nome, laco):
    while True:
        try:
            laco()
            print(f"[{nome}] laço terminou; reiniciando", flush=True)
        except Exception:
            print(f"[{nome}] erro, reiniciando em {ESPERA_REINICIO}s:\n"
                  f"{traceback.format_exc()}", flush=True)
        time.sleep(ESPERA_REINICIO)


def main():
    if os.geteuid() != 0:
        sys.exit("Precisa rodar como root (é um serviço de sistema).")
    for nome, laco in (("uplink", uplink_guard.laco),
                       ("led", opendongle_led.laco),
                       ("descoberta", opendongle_discovery.laco)):
        threading.Thread(target=_supervisionar, args=(nome, laco),
                         name=nome, daemon=True).start()
    # painel na thread principal: se ele cair, o processo sai e o systemd
    # (Restart=always) reinicia tudo
    opendongle_web.servir()


if __name__ == "__main__":
    main()
