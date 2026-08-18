#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
instalar_opendongle.py — instala o painel OpenDongle no dongle (roda no PC)
============================================================================
Coloca no dongle, via SSH:
  - motor único + CLI + painel web (em /opt/opendongle)
  - comando `opendongle` em /usr/local/bin (a CLI)
  - serviço systemd do painel web (porta 80)
  - serviço systemd do uplink guard (gateway condicional)
  - serviço systemd dos LEDs (papel USB, modo Wi-Fi, internet, áudio)
  - usb-role-autosense.sh (grupos, Bluetooth, papel USB, 4G plug-and-play)
  - avahi configurado para responder opendongle.local
  - garante o SSID/senha padrão do hotspot: OpenDongle / opendongle
  - reinicia o dongle no final, pra ativar o usb-role-autosense de vez
    (ele só decide o papel USB corretamente longe de uma instalação SSH
    em andamento — ver nota no [2/6])
  - depois do reboot, espera o dongle voltar e roda um teste geral:
    serviços ativos, papel USB, avahi, o motor respondendo de fato, e um
    diagnóstico de hardware (áudio, Bluetooth, vídeo USB, modem 4G) —
    termina com "Sua instalação está terminada" e a lista do que precisa
    de atenção manual, se houver

Uso:
  python3 instalar_opendongle.py --ip 192.168.100.1 --senha 1
"""

import argparse
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent / "opendongle"
ARQS = ["opendongle_engine.py", "opendongle_cli.py", "opendongle_web.py",
        "uplink_guard.py", "opendongle_led.py", "opendongle_diag.py",
        "usb-role-autosense.sh"]

UNIT = """[Unit]
Description=OpenDongle painel web
After=network.target NetworkManager.service

[Service]
ExecStart=/usr/bin/python3 /opt/opendongle/opendongle_web.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""

# Serviço do uplink_guard: só anuncia gateway quando há internet de fato,
# resolvendo o "dongle sem SIM derruba a internet do PC".
UNIT_UPLINK = """[Unit]
Description=OpenDongle uplink guard (gateway condicional)
After=network.target dnsmasq.service

[Service]
ExecStart=/usr/bin/python3 /opt/opendongle/uplink_guard.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""

# Serviço dos LEDs: red:power/green:wlan/blue:wan contam papel USB (device/
# host), modo Wi-Fi (cliente/hotspot) e internet sem precisar de SSH.
# NÃO ordenar com "After=usb-role-autosense.service" aqui: esse serviço tem
# "After=multi-user.target" (proposital, definido em bancada — ver
# UNIT_USBROLE), e como opendongle-led.service é WantedBy=multi-user.target
# (logo, Before= implícito), isso fecha um ciclo de dependência que o
# systemd resolve descartando o job do LED silenciosamente em todo boot
# (visto ao vivo: "Found ordering cycle on opendongle-led.service/start").
# O script já faz polling a cada poucos segundos e se autocorrige sozinho,
# não precisa de ordem estrita de boot.
UNIT_LED = """[Unit]
Description=OpenDongle LED (papel USB, modo Wi-Fi, internet e áudio)
After=network.target NetworkManager.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/opendongle/opendongle_led.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
"""

# usb-role-autosense.sh: grupos de acesso, Bluetooth, decide papel USB
# (device/host) e, em host, conecta o 4G plug-and-play (SIM -> APN).
# Unidade idêntica à testada em bancada (dongle/context.md, seção 10).
UNIT_USBROLE = """[Unit]
Description=Ensina o papel USB conforme o contexto de conexao (PC vs externo)
After=multi-user.target
StartLimitIntervalSec=0

[Service]
Type=oneshot
ExecStart=/usr/local/bin/usb-role-autosense.sh
StandardOutput=journal
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""

# avahi: publica o host como opendongle.local (mDNS)
AVAHI_HOSTNAME = "opendongle"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.100.1")
    ap.add_argument("--usuario", default="user")
    ap.add_argument("--senha", default="1")
    args = ap.parse_args()

    for a in ARQS:
        if not (BASE / a).exists():
            sys.exit(f"faltando: opendongle/{a} ao lado deste script.")
    try:
        socket.create_connection((args.ip, 22), timeout=5).close()
    except OSError:
        sys.exit(f"{args.ip}:22 não responde. Dongle conectado?")

    # SSH robusto de bancada: chave primeiro, sshpass como fallback,
    # sempre ignorando known_hosts (reflash de vários dongles no mesmo IP).
    ssh_base = ["-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "ConnectTimeout=10", "-o", "LogLevel=ERROR"]
    try:
        chave_ok = subprocess.run(
            ["ssh", "-o", "BatchMode=yes"] + ssh_base +
            [f"{args.usuario}@{args.ip}", "true"],
            capture_output=True, timeout=15).returncode == 0
    except Exception:
        chave_ok = False
    if chave_ok:
        ssh = ["ssh"] + ssh_base + [f"{args.usuario}@{args.ip}"]
    elif shutil.which("sshpass"):
        ssh = ["sshpass", "-p", args.senha, "ssh"] + ssh_base + \
            [f"{args.usuario}@{args.ip}"]
    else:
        print("(sem chave SSH nem sshpass — a senha será pedida)")
        ssh = ["ssh"] + ssh_base + [f"{args.usuario}@{args.ip}"]

    print("== [1/6] Enviando arquivos do painel...")
    # manda os 3 arquivos via tar por stdin (uma conexão)
    import tarfile, io
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for a in ARQS:
            t.add(BASE / a, arcname=a)
    # passa os BYTES via input= (BytesIO como stdin quebra: não tem fileno)
    r = subprocess.run(ssh + ["cat > /tmp/opendongle.tar"],
                       input=buf.getvalue())
    if r.returncode != 0:
        sys.exit("Falha no envio (senha errada?).")

    print("== [2/6] Instalando motor, CLI e serviços (sudo)...")
    # usb-role-autosense.service NÃO sobe com --now de propósito: a própria
    # instalação está rodando por SSH sobre a rede USB (RNDIS = papel
    # "device"). Se o script reavaliar o papel USB agora e, por qualquer
    # instabilidade momentânea, decidir "host", a instalação perde a
    # conexão no meio do processo (isso já aconteceu em teste de bancada —
    # ver dongle/context.md). Fica "enabled" e só entra em vigor no
    # PRÓXIMO boot, quando não há uma instalação em andamento disputando
    # a mesma interface.
    remoto = (
        "sudo -S bash -c '"
        "mkdir -p /opt/opendongle && "
        "tar xf /tmp/opendongle.tar -C /opt/opendongle && "
        "rm /tmp/opendongle.tar && "
        "chmod 755 /opt/opendongle/*.py /opt/opendongle/*.sh && "
        "cp /opt/opendongle/usb-role-autosense.sh /usr/local/bin/usb-role-autosense.sh && "
        "chmod 755 /usr/local/bin/usb-role-autosense.sh && "
        # Corrige bug conhecido do ifupdown2 em imagens Debian 13/Python
        # 3.12+: RawConfigParser.readfp foi removido do Python, ifupdown2
        # crasha ao ler sua config e a bridge br0 (192.168.100.1, usada
        # por ESTE PRÓPRIO SSH) nunca sobe sozinha em NENHUM boot. Sem
        # isso, a rede USB simplesmente não existe até alguém consertar
        # na mão pelo console serial (foi assim que achamos o bug).
        "f=/usr/share/ifupdown2/ifupdown/main.py; "
        "if [ -f \"$f\" ] && grep -q \"parser\\.readfp(configFP)\" \"$f\"; then "
        "sed -i \"s/parser\\.readfp(configFP)/parser.read_file(configFP)/\" \"$f\"; "
        "rm -f /usr/share/ifupdown2/ifupdown/__pycache__/*.pyc 2>/dev/null; "
        "echo \"fix: ifupdown2 readfp corrigido (Debian 13/Python 3.12+)\"; "
        "fi; "
        # bridge-ports genérico da imagem assume usb0+usb1 (RNDIS+ECM),
        # mas boards com só RNDIS habilitado (ECM/NCM=0) nunca têm usb1 —
        # ajusta só quando essa condição bate, pra não mexer em boards
        # que realmente usam os dois.
        "gc=/etc/msm8916-usb-gadget.conf; ni=/etc/network/interfaces; "
        "if [ -f \"$gc\" ] && [ -f \"$ni\" ] && grep -q \"^ENABLE_ECM=0\" \"$gc\" "
        "&& grep -q \"^ENABLE_NCM=0\" \"$gc\" && grep -q \"bridge-ports usb0 usb1\" \"$ni\"; then "
        "sed -i \"s/bridge-ports usb0 usb1/bridge-ports usb0/\" \"$ni\"; "
        "echo \"fix: bridge-ports ajustado pra usb0 (ECM/NCM desligados nesse board)\"; "
        "fi && "
        # CLI acessível como 'opendongle'
        "printf \"#!/bin/sh\\nexec /usr/bin/python3 "
        "/opt/opendongle/opendongle_cli.py \\\"\\$@\\\"\\n\" "
        "> /usr/local/bin/opendongle && chmod 755 /usr/local/bin/opendongle && "
        # serviço web
        "cat > /etc/systemd/system/opendongle.service << \"EOF\"\n"
        + UNIT +
        "EOF\n"
        "cat > /etc/systemd/system/opendongle-uplink.service << \"EOF\"\n"
        + UNIT_UPLINK +
        "EOF\n"
        "cat > /etc/systemd/system/opendongle-led.service << \"EOF\"\n"
        + UNIT_LED +
        "EOF\n"
        "cat > /etc/systemd/system/usb-role-autosense.service << \"EOF\"\n"
        + UNIT_USBROLE +
        "EOF\n"
        "systemctl daemon-reload && "
        "systemctl enable --now opendongle.service && "
        "systemctl enable --now opendongle-uplink.service && "
        "systemctl enable --now opendongle-led.service && "
        "systemctl enable usb-role-autosense.service && "
        "sleep 2 && systemctl is-active opendongle.service'"
    )
    r = subprocess.run(ssh + [remoto],
                       input=(args.senha + "\n").encode(),
                       capture_output=True)
    out = r.stdout.decode(errors="replace")
    print(out)
    if "active" not in out:
        print(r.stderr.decode(errors="replace")[-400:])
        sys.exit("Serviço web não subiu — veja a saída acima.")

    print("== [3/6] Configurando avahi (opendongle.local)...")
    avahi = (
        "sudo -S bash -c '"
        # reativa o avahi (o otimizador desliga por RAM; ligamos p/ .local)
        "DEBIAN_FRONTEND=noninteractive apt-get install -y avahi-daemon "
        ">/dev/null 2>&1 || true; "
        "systemctl unmask avahi-daemon 2>/dev/null; "
        f"hostnamectl set-hostname {AVAHI_HOSTNAME} 2>/dev/null || "
        f"(echo {AVAHI_HOSTNAME} > /etc/hostname; "
        f"hostname {AVAHI_HOSTNAME}); "
        # CRÍTICO: registrar o hostname no /etc/hosts, senão 'sudo' e
        # outros reclamam \"unable to resolve host\" e ficam lentos.
        # Aspas DUPLAS aqui de propósito: isto tudo já está dentro de um
        # bash -c '...' com aspas simples — aspas simples aninhadas
        # fecham a string cedo demais e quebram o resto do comando.
        f'grep -q "127.0.1.1[[:space:]]*{AVAHI_HOSTNAME}" /etc/hosts || '
        f'echo "127.0.1.1 {AVAHI_HOSTNAME}" >> /etc/hosts; '
        # garante que o avahi publica o hostname na rede (mDNS)
        'sed -i "s/^#*host-name=.*/host-name=' + AVAHI_HOSTNAME + '/" '
        "/etc/avahi/avahi-daemon.conf 2>/dev/null || true; "
        'sed -i "s/^#*publish-workstation=.*/publish-workstation=yes/" '
        "/etc/avahi/avahi-daemon.conf 2>/dev/null || true; "
        # avahi precisa ouvir na interface da rede USB (não só wlan)
        "systemctl enable avahi-daemon >/dev/null 2>&1; "
        "systemctl restart avahi-daemon >/dev/null 2>&1; "
        "sleep 1; systemctl is-active avahi-daemon'"
    )
    r = subprocess.run(ssh + [avahi],
                       input=(args.senha + "\n").encode(),
                       capture_output=True)
    estado_avahi = r.stdout.decode(errors="replace").strip()
    print("   avahi:", estado_avahi or "?")
    if "active" not in estado_avahi:
        print("   ⚠ avahi não ativou — opendongle.local pode não resolver. "
              "Use o IP 192.168.100.1 como alternativa.")

    print("== [4/6] Garantindo hotspot padrão OpenDongle/opendongle...")
    hs = (
        "sudo -S /opt/opendongle/opendongle_cli.py hotspot "
        "--ssid OpenDongle --senha opendongle"
    )
    r = subprocess.run(ssh + [hs],
                       input=(args.senha + "\n").encode(),
                       capture_output=True)
    print("   " + (r.stdout.decode(errors="replace").strip()
                   or r.stderr.decode(errors="replace").strip()[:120]))

    print("""
== OpenDongle instalado! ==
No dongle:
  sudo opendongle status
Do celular/PC:
  conecte no Wi-Fi 'OpenDongle' (senha: opendongle)
  abra  http://opendongle.local   (ou http://192.168.100.1)

Os LEDs físicos (vermelho/verde/azul) agora contam o estado do dongle sem
precisar de SSH: papel USB, modo Wi-Fi (cliente/hotspot), internet e erro.

Observações honestas:
- opendongle.local depende de mDNS: funciona em Android/Mac/Linux; em
  alguns Windows falha — por isso a tela sempre mostra o IP como plano B.
- Ao trocar nome/senha do hotspot, os clientes caem e precisam
  reconectar (a página avisa isso ao usuário).
""")

    print("== [5/6] Reiniciando o dongle para ativar o usb-role-autosense...")
    # dispara o reboot em background, desanexado da sessão SSH: o 'sleep 2'
    # dá tempo do comando 'ssh' retornar normalmente antes da conexão cair
    # (sem isso, o subprocess.run ficaria esperando uma resposta que nunca
    # chega, porque o reboot derruba a rede USB no meio da resposta).
    reboot = (
        "sudo -S bash -c "
        "'nohup sh -c \"sleep 2 && reboot\" >/dev/null 2>&1 & disown'"
    )
    try:
        subprocess.run(ssh + [reboot], input=(args.senha + "\n").encode(),
                       capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        pass   # esperado se a conexão já tiver caído — o reboot já foi disparado

    print("== [6/6] Esperando o dongle voltar pra rodar o teste geral...")
    voltou = False
    prazo = time.time() + 120
    time.sleep(5)   # dá um respiro antes da 1ª tentativa (a rede cai na hora)
    while time.time() < prazo:
        try:
            socket.create_connection((args.ip, 22), timeout=3).close()
            voltou = True
            break
        except OSError:
            time.sleep(3)

    if not voltou:
        print("   ⚠ SSH não voltou em ~2min. Pode ser boot mais lento — "
              "tente 'sudo opendongle status' manualmente daqui a pouco, "
              "ou veja /var/log/usb-role-autosense.log pelo console serial "
              "se o papel USB não tiver resolvido pra 'device'.")
        sys.exit(1)

    print("   dongle respondeu — rodando checagens:")
    checagens = [
        ("serviço painel web",         "systemctl is-active opendongle.service"),
        ("serviço uplink guard",       "systemctl is-active opendongle-uplink.service"),
        ("serviço LEDs",               "systemctl is-active opendongle-led.service"),
        ("serviço usb-role-autosense", "systemctl is-active usb-role-autosense.service"),
        ("avahi (opendongle.local)",   "systemctl is-active avahi-daemon"),
        ("papel USB (informativo)",    "cat /sys/class/usb_role/ci_hdrc.0-role-switch/role"),
    ]
    problemas = []   # [(nome, detalhe)] — só o que realmente falhou
    for nome, cmd in checagens:
        r = subprocess.run(ssh + [cmd], capture_output=True, timeout=15)
        saida = (r.stdout.decode(errors="replace").strip()
                 or r.stderr.decode(errors="replace").strip())
        ok = r.returncode == 0
        print(f"   {'✅' if ok else '❌'} {nome}: {saida[:80]}")
        if not ok:
            problemas.append((nome, saida[:120] or "comando falhou"))

    # teste funcional de verdade: o motor respondendo, não só o serviço "up"
    r = subprocess.run(
        ssh + ["sudo -S /opt/opendongle/opendongle_cli.py --json status"],
        input=(args.senha + "\n").encode(), capture_output=True, timeout=20)
    try:
        res = json.loads(r.stdout.decode(errors="replace").strip())
    except (ValueError, UnicodeDecodeError):
        res = {}
    if res.get("ok"):
        print(f"   ✅ motor (opendongle status): modo={res.get('modo')} "
              f"internet={res.get('internet')}")
    else:
        detalhe = r.stdout.decode(errors="replace").strip()[:120]
        print(f"   ❌ motor (opendongle status) não respondeu como esperado: {detalhe}")
        problemas.append(("motor (opendongle status)", detalhe or "sem resposta"))

    print("\n   -- hardware: áudio, Bluetooth, vídeo USB e modem 4G --")
    r = subprocess.run(
        ssh + ["sudo -S /opt/opendongle/opendongle_diag.py --json"],
        input=(args.senha + "\n").encode(), capture_output=True, timeout=40)
    try:
        diag_resultados = json.loads(r.stdout.decode(errors="replace").strip())
    except (ValueError, UnicodeDecodeError):
        diag_resultados = None

    if diag_resultados is None:
        detalhe = r.stdout.decode(errors="replace").strip()[:120]
        print(f"   ❌ diagnóstico de hardware não respondeu: {detalhe}")
        problemas.append(("diagnóstico de hardware", detalhe or "sem resposta"))
    else:
        icone = {"ok": "✅", "falha": "❌", "nao_testavel": "➖"}
        for item in diag_resultados:
            print(f"   {icone.get(item['status'], '?')} {item['nome']}: {item['detalhe']}")
            if item["status"] == "falha":
                problemas.append((item["nome"], item["detalhe"]))

    print()
    if not problemas:
        print("== Sua instalação está terminada. Tudo funcionando. ==")
    else:
        print("== Sua instalação está terminada, com ressalvas: ==")
        for nome, detalhe in problemas:
            print(f"   ✗ {nome}: {detalhe} — tentar resolver manualmente.")
        sys.exit(1)


if __name__ == "__main__":
    main()
