#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uplink_guard.py — só se anuncia como "provedor de internet" quando TEM
=====================================================================
Roda NO DONGLE como serviço. Resolve o problema clássico: um dongle sem
SIM/4G, plugado no PC, faz o PC achar que ele é o caminho pra internet
e o PC perde a conexão real (Wi-Fi). Isso trava updates e confunde o
usuário.

Lógica (exatamente a pedida):
  - a cada X segundos, verifica se o dongle tem uplink REAL de internet
    (ping de saída por uma interface que NÃO seja a rede USB local);
  - TEM uplink  -> anuncia o dongle como gateway (dhcp-option router);
  - NÃO tem     -> NÃO anuncia gateway. O PC do cliente então não elege
    o dongle como rota de internet e mantém a própria conexão.

Assim a correção mora no DONGLE: funciona para qualquer PC que plugar,
sem precisar configurar nada no PC do cliente.

Sem dependências externas: stdlib + dnsmasq (já presente na imagem).
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opendongle_engine as eng

# Arquivo de config incremental lido pelo dnsmasq do OpenStick.
# Escrevemos AQUI o anúncio (ou a ausência) do gateway.
DROPIN = "/etc/dnsmasq.d/zz-uplink-gateway.conf"
INTERVALO = 15            # segundos entre checagens


def escrever_estado(anunciar_gateway):
    """
    Reescreve o drop-in do dnsmasq conforme o estado do uplink.
      anunciar_gateway=True  -> option:router = IP do dongle (é gateway)
      anunciar_gateway=False -> option:router VAZIO = 'não sou gateway'
                                + option:dns vazio (não sou DNS de saída)
    Só reescreve+recarrega se MUDOU (evita restart à toa do dnsmasq).
    """
    if anunciar_gateway:
        conteudo = (
            "# gerado por uplink_guard: dongle COM internet -> é gateway\n"
            f"dhcp-option=tag:br0,option:router,{eng.ip_lan()}\n"
        )
    else:
        # router vazio = RFC: cliente NÃO instala rota default via dongle.
        conteudo = (
            "# gerado por uplink_guard: dongle SEM internet -> NÃO é gateway\n"
            "dhcp-option=tag:br0,option:router\n"
            "dhcp-option=tag:br0,option:dns-server\n"
        )
    atual = ""
    if os.path.exists(DROPIN):
        try:
            atual = open(DROPIN).read()
        except OSError:
            atual = ""
    if atual == conteudo:
        return False   # nada mudou
    # temporário fora de /etc/dnsmasq.d (o dnsmasq leria um .tmp esquecido
    # lá), mas no mesmo sistema de arquivos pro os.replace ser atômico
    os.makedirs("/etc/opendongle", mode=0o700, exist_ok=True)
    tmp = "/etc/opendongle/.gravando-uplink-gateway"
    with open(tmp, "w") as f:
        f.write(conteudo)
    os.replace(tmp, DROPIN)
    # restart, não reload: o SIGHUP do dnsmasq não relê dhcp-option do
    # conf-dir, então o anúncio do gateway não mudava de verdade
    eng._run(["systemctl", "restart", "dnsmasq"], timeout=15)
    return True


def laco():
    """Renova o estado de internet a cada INTERVALO e ajusta o anúncio de
    gateway. Roda como thread do opendongled (ou sozinho pelo main)."""
    ultimo = None
    while True:
        estado = eng.tem_internet(max_idade=0)
        if estado != ultimo:
            mudou = escrever_estado(estado)
            if mudou:
                print(("UPLINK OK -> anunciando gateway"
                       if estado else
                       "SEM uplink -> NÃO anuncio gateway (PC mantém sua "
                       "internet)"), flush=True)
            ultimo = estado
        time.sleep(INTERVALO)


if __name__ == "__main__":
    # modo teste: 'python3 uplink_guard.py once' imprime o estado e sai
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        print("tem_uplink:", eng.tem_internet(max_idade=0))
        print("interfaces candidatas:", eng.interfaces_uplink())
        sys.exit(0)
    if os.geteuid() != 0:
        sys.exit("Precisa rodar como root (é um serviço de sistema).")
    try:
        laco()
    except KeyboardInterrupt:
        pass
