#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongle_discovery.py — responde "aqui estou" na rede local (roda no dongle)
================================================================================
Sem mDNS funcionando (alguns Windows não resolvem opendongle.local) e sem
querer depender de USB ou de abrir o roteador, o jeito que sobra é o dongle
se anunciar sozinho: fica ouvindo um probe UDP de broadcast e responde por
unicast pro remetente. O IP de origem do pacote de resposta, visto do lado
do PC, já É o endereço certo pra abrir o painel — não precisa o dongle
descobrir o próprio IP (resolve sozinho o caso de múltiplas interfaces).

Ver opendongle_localizar.py (raiz do repo) pro lado que roda no PC.
"""
import json
import socket

PORTA = 40404
PROBE = b"OPENDONGLE_DISCOVER_V1"


def _id_aparelho():
    try:
        with open("/etc/opendongle/id") as f:
            return f.read().strip()
    except OSError:
        return ""


def laco():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", PORTA))
    resposta = json.dumps({
        "tipo": "OPENDONGLE_HELLO_V1",
        "host": socket.gethostname(),
        # a mesma identidade do /api/ola: distingue vários dongles na mesma rede
        "id": _id_aparelho(),
    }).encode()

    while True:
        try:
            dados, endereco = s.recvfrom(256)
        except OSError:
            continue
        if dados == PROBE:
            try:
                s.sendto(resposta, endereco)
            except OSError:
                pass


if __name__ == "__main__":
    laco()
