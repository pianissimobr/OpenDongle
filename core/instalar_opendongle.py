#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
instalar_opendongle.py — instala o painel OpenDongle no dongle (roda no PC)
============================================================================
Coloca no dongle, via SSH:
  - motor único + CLI + painel web (em /opt/opendongle)
  - comando `opendongle` em /usr/local/bin (a CLI)
  - serviço systemd do painel web (porta 80)
  - avahi configurado para responder opendongle.local
  - garante o SSID/senha padrão do hotspot: OpenDongle / opendongle

Uso:
  python3 instalar_opendongle.py --ip 192.168.100.1 --senha 1
"""

import argparse
import shutil
import socket
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent / "opendongle"
ARQS = ["opendongle_engine.py", "opendongle_cli.py", "opendongle_web.py",
        "uplink_guard.py"]

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

    print("== [1/4] Enviando arquivos do painel...")
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

    print("== [2/4] Instalando motor, CLI e serviço web (sudo)...")
    remoto = (
        "sudo -S bash -c '"
        "mkdir -p /opt/opendongle && "
        "tar xf /tmp/opendongle.tar -C /opt/opendongle && "
        "rm /tmp/opendongle.tar && "
        "chmod 755 /opt/opendongle/*.py && "
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
        "systemctl daemon-reload && "
        "systemctl enable --now opendongle.service && "
        "systemctl enable --now opendongle-uplink.service && "
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

    print("== [3/4] Configurando avahi (opendongle.local)...")
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
        f"grep -q '127.0.1.1[[:space:]]*{AVAHI_HOSTNAME}' /etc/hosts || "
        f"echo '127.0.1.1 {AVAHI_HOSTNAME}' >> /etc/hosts; "
        # garante que o avahi publica o hostname na rede (mDNS)
        "sed -i 's/^#*host-name=.*/host-name=" + AVAHI_HOSTNAME + "/' "
        "/etc/avahi/avahi-daemon.conf 2>/dev/null || true; "
        "sed -i 's/^#*publish-workstation=.*/publish-workstation=yes/' "
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

    print("== [4/4] Garantindo hotspot padrão OpenDongle/opendongle...")
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

Observações honestas:
- opendongle.local depende de mDNS: funciona em Android/Mac/Linux; em
  alguns Windows falha — por isso a tela sempre mostra o IP como plano B.
- Ao trocar nome/senha do hotspot, os clientes caem e precisam
  reconectar (a página avisa isso ao usuário).
""")


if __name__ == "__main__":
    main()
