#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongle_proxy.py — porta 80 sempre atendida, painel web só quando usado
============================================================================
Roda dentro do opendongled (processo que já fica ligado). Só stdlib de
socket: nada de http.server aqui, pra não custar RAM no processo permanente.

  painel acordado  -> repassa os bytes pro socket unix do opendongle-web
  painel dormindo  -> GET de página: responde na hora "Carregando painel…",
                      acorda o painel e a página recarrega quando ele subir;
                      demais pedidos: repassa e espera ele subir (1–2 s)

O painel (opendongle-web.service) é ativado pelo systemd no primeiro acesso
ao socket e se encerra sozinho depois de um tempo ocioso.
"""

import os
import select
import socket
import threading
import time

PORTA = 80
SOCKET_WEB = "/run/opendongle/web.sock"
FLAG_PRONTO = "/run/opendongle/web-pronto"   # criada pelo painel ao subir
MAX_CABECALHO = 16384
ESPERA_REPASSE = 60   # segundos sem tráfego antes de largar a conexão
REACORDAR = 5         # "Carregando painel…" pede de novo se o painel não subiu
_ULTIMO_ACORDAR = [0.0]

PAGINA_CARREGANDO = """<!doctype html><html lang='pt-br'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Carregando painel…</title>
<noscript><meta http-equiv='refresh' content='3'></noscript>
<style>
:root{--bg:#f4f6fb;--tx:#1b2436;--mut:#5b6b88;--ac:#2f6fe4}
@media (prefers-color-scheme:dark){:root{--bg:#0b1220;--tx:#e6ecf7;--mut:#8ea0c4;--ac:#4f8cff}}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
 background:var(--bg);color:var(--tx);font-family:system-ui,sans-serif;text-align:center}
.giro{width:42px;height:42px;margin:0 auto 18px;border-radius:50%;
 border:4px solid color-mix(in srgb,var(--ac) 25%,transparent);border-top-color:var(--ac);
 animation:g 0.9s linear infinite}@keyframes g{to{transform:rotate(360deg)}}
p{color:var(--mut);margin:6px 0}
</style></head><body><div><div class='giro'></div>
<h2>Carregando painel…</h2><p>O painel dorme quando ninguém usa, pra poupar memória.</p>
</div><script>
(function espera(){fetch('/__estado',{cache:'no-store'}).then(r=>r.text()).then(t=>{
 if(t==='1'){location.reload()}else{setTimeout(espera,300)}}).catch(()=>setTimeout(espera,600))})();
</script></body></html>"""


def _pronto():
    return os.path.exists(FLAG_PRONTO)


def _responder(conexao, status, tipo, corpo):
    dados = corpo.encode()
    conexao.sendall(
        f"HTTP/1.0 {status}\r\nContent-Type: {tipo}\r\nContent-Length: {len(dados)}\r\n"
        "Cache-Control: no-store\r\nConnection: close\r\n\r\n".encode() + dados)


def _acordar():
    """Conectar no socket já faz o systemd subir o painel. Lê a resposta até o
    fim: fechar antes faz o painel registrar "Broken pipe" a cada partida."""
    _ULTIMO_ACORDAR[0] = time.monotonic()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(30)
            s.connect(SOCKET_WEB)
            s.sendall(b"GET /__ping HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
            while s.recv(4096):
                pass
    except OSError:
        pass


def _repassar(cliente, inicio):
    try:
        painel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        painel.settimeout(15)            # tempo pro systemd subir o painel
        painel.connect(SOCKET_WEB)
        painel.settimeout(None)
    except OSError:
        _responder(cliente, "503 Service Unavailable", "text/plain; charset=utf-8",
                   "Painel indisponível no momento.")
        return
    with painel:
        painel.sendall(inicio)
        pares = {cliente: painel, painel: cliente}
        abertos = {cliente, painel}
        while abertos:
            prontos, _, _ = select.select(list(abertos), [], [], ESPERA_REPASSE)
            if not prontos:
                return
            for origem in prontos:
                try:
                    dados = origem.recv(65536)
                except OSError:
                    dados = b""
                destino = pares[origem]
                if not dados:
                    abertos.discard(origem)
                    try:
                        destino.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                    if origem is painel:   # resposta completa: encerra
                        return
                    continue
                try:
                    destino.sendall(dados)
                except OSError:
                    return


def _atender(cliente):
    with cliente:
        cliente.settimeout(15)
        inicio = b""
        try:
            while b"\r\n\r\n" not in inicio and len(inicio) < MAX_CABECALHO:
                parte = cliente.recv(4096)
                if not parte:
                    return
                inicio += parte
        except OSError:
            return
        primeira = inicio.split(b"\r\n", 1)[0].decode("latin-1", "replace").split()
        metodo = primeira[0] if primeira else ""
        caminho = primeira[1] if len(primeira) > 1 else "/"
        cabecalho = inicio.split(b"\r\n\r\n", 1)[0].lower()

        if caminho == "/__estado":
            pronto = _pronto()
            # se o primeiro pedido se perdeu (ou o painel caiu ao subir), a
            # página de espera não fica girando pra sempre
            if not pronto and time.monotonic() - _ULTIMO_ACORDAR[0] > REACORDAR:
                threading.Thread(target=_acordar, daemon=True).start()
            _responder(cliente, "200 OK", "text/plain", "1" if pronto else "0")
            return
        if (not _pronto() and metodo == "GET" and b"text/html" in cabecalho
                and not caminho.startswith("/api/")):
            threading.Thread(target=_acordar, daemon=True).start()
            _responder(cliente, "200 OK", "text/html; charset=utf-8", PAGINA_CARREGANDO)
            return
        cliente.settimeout(None)
        _repassar(cliente, inicio)


def laco():
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor.bind(("0.0.0.0", PORTA))
    servidor.listen(32)
    while True:
        cliente, _ = servidor.accept()
        threading.Thread(target=_atender, args=(cliente,), daemon=True).start()
