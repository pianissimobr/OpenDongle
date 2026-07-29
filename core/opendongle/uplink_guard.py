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
import subprocess
import sys
import time

# Arquivo de config incremental lido pelo dnsmasq do OpenStick.
# Escrevemos AQUI o anúncio (ou a ausência) do gateway.
DROPIN = "/etc/dnsmasq.d/zz-uplink-gateway.conf"
IP_LOCAL = "192.168.100.1"
REDE_LOCAL = "192.168.100."
INTERVALO = 15            # segundos entre checagens
HOSTS_TESTE = ["1.1.1.1", "8.8.8.8"]   # alvos de ping para aferir uplink


def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout.strip()
    except Exception:
        return 1, ""


def interfaces_uplink():
    """Lista interfaces que NÃO são a rede USB local — candidatas a uplink
    real (o modem 4G aparece como wwan0/ppp0; Wi-Fi cliente como wlan0)."""
    rc, out = _run(["ip", "-o", "-4", "addr", "show"])
    ifaces = []
    for linha in out.splitlines():
        partes = linha.split()
        if len(partes) >= 4:
            nome, addr = partes[1], partes[3]
            # ignora a interface da rede local do dongle (br0/usb com .100.x)
            if REDE_LOCAL in addr:
                continue
            if nome == "lo":
                continue
            ifaces.append(nome)
    return ifaces


def tem_uplink():
    """
    True só se conseguir SAIR pra internet por uma interface que não seja
    a rede local. Testa ping amarrado a cada interface candidata; se
    qualquer uma alcança a internet, há uplink.
    """
    candidatas = interfaces_uplink()
    if not candidatas:
        return False
    for iface in candidatas:
        for host in HOSTS_TESTE:
            rc, _ = _run(["ping", "-c", "1", "-W", "2", "-I", iface, host],
                         timeout=6)
            if rc == 0:
                return True
    return False


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
            f"dhcp-option=tag:br0,option:router,{IP_LOCAL}\n"
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
    tmp = DROPIN + ".tmp"
    with open(tmp, "w") as f:
        f.write(conteudo)
    os.replace(tmp, DROPIN)  # troca atomica
    # recarrega o dnsmasq (SIGHUP relê drop-ins sem derrubar o serviço)
    _run(["systemctl", "reload", "dnsmasq"], timeout=15)
    return True


def main():
    if os.geteuid() != 0:
        sys.exit("Precisa rodar como root (é um serviço de sistema).")
    ultimo = None
    while True:
        estado = tem_uplink()
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
        print("tem_uplink:", tem_uplink())
        print("interfaces candidatas:", interfaces_uplink())
        sys.exit(0)
    try:
        main()
    except KeyboardInterrupt:
        pass
