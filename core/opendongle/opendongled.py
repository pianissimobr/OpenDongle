#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongled.py — o que precisa ficar sempre ligado, num processo Python só
============================================================================
Threads do mesmo processo: uplink guard, LEDs, descoberta na rede e o
repassador da porta 80. O painel web NÃO mora aqui: ele é um serviço à
parte (opendongle-web), ativado pelo systemd no primeiro acesso e encerrado
quando fica ocioso — o repassador mostra "Carregando painel…" enquanto ele
sobe. Assim o http.server e as telas não ocupam RAM com ninguém usando.

Cada thread tem um supervisor: se o laço morrer por exceção, ele registra
no journal e reinicia só aquela parte.
"""

import os
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opendongle_discovery
import opendongle_led
import opendongle_proxy
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
    # porta 80 na thread principal: se ela cair, o processo sai e o systemd
    # (Restart=always) reinicia tudo
    opendongle_proxy.laco()


if __name__ == "__main__":
    main()
