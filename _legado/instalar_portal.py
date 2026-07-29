#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
instalar_portal.py — Instala o portal cativo no dongle via SSH (roda no PC)

  python3 instalar_portal.py                # dongle em 192.168.100.1
  python3 instalar_portal.py --senha X --ip Y

O que faz no dongle:
  - copia portal/portal.py para /opt/portal/
  - cria e habilita o serviço systemd portal.service (sobe em todo boot)
  - inicia agora; na primeira conexão de alguém ao hotspot, o portal
    aparece pedindo login do sistema (ex.: user / 1)
"""

import argparse
import shutil
import subprocess
import sys
import socket
from pathlib import Path

BASE = Path(__file__).resolve().parent
PORTAL = BASE / "portal" / "portal.py"

UNIT = """[Unit]
Description=Portal cativo OpenStick
After=network.target NetworkManager.service

[Service]
ExecStart=/usr/bin/python3 /opt/portal/portal.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.100.1")
    ap.add_argument("--usuario", default="user")
    ap.add_argument("--senha", default="1",
                    help="senha SSH/sudo do dongle (padrão: 1)")
    args = ap.parse_args()

    if not PORTAL.exists():
        sys.exit("portal/portal.py não encontrado ao lado deste script.")
    try:
        socket.create_connection((args.ip, 22), timeout=5).close()
    except OSError:
        sys.exit(f"{args.ip}:22 não responde. Dongle conectado?")

    ssh = (["sshpass", "-p", args.senha] if shutil.which("sshpass") else []) \
        + ["ssh", "-o", "StrictHostKeyChecking=accept-new",
           f"{args.usuario}@{args.ip}"]
    if not shutil.which("sshpass"):
        print("(sem sshpass — a senha será pedida algumas vezes)")

    print("== [1/3] Enviando portal.py...")
    r = subprocess.run(ssh + ["cat > /tmp/portal.py"],
                       stdin=open(PORTAL, "rb"))
    if r.returncode != 0:
        sys.exit("Falha no envio (senha errada?).")

    print("== [2/3] Instalando serviço (sudo no dongle)...")
    remoto = (
        "sudo -S bash -c '"
        "mkdir -p /opt/portal && mv /tmp/portal.py /opt/portal/portal.py && "
        "chmod 755 /opt/portal/portal.py && "
        "cat > /etc/systemd/system/portal.service << \"EOF\"\n"
        + UNIT +
        "EOF\n"
        "systemctl daemon-reload && systemctl enable --now portal.service && "
        "sleep 2 && systemctl is-active portal.service'"
    )
    r = subprocess.run(ssh + [remoto], input=(args.senha + "\n").encode(),
                       capture_output=True)
    saida = r.stdout.decode(errors="replace")
    print(saida)
    if "active" not in saida:
        print(r.stderr.decode(errors="replace")[-400:])
        sys.exit("Serviço não subiu — me mande a saída acima.")

    print("== [3/3] Portal instalado e ATIVO!")
    print("""
Teste: esqueça a rede 4G-UFI-XX no celular, reconecte — o pop-up
'Fazer login na rede' deve aparecer (ou abra http://192.168.100.1).
Login: credenciais do sistema (ex.: user / 1).

Observações importantes:
- O portal só exige login na PRIMEIRA conexão após ligar o modem na
  energia (a flag vive em /run, que zera a cada energização).
- Se alguém escolher 'conectar a um Wi-Fi', o hotspot DESLIGA e o
  modem vira cliente daquela rede (limitação do chip). Para voltar ao
  modo hotspot: via USB/SSH, rode
    sudo nmcli connection up Hotspot
- A senha viaja em HTTP puro dentro da rede local do hotspot — troque
  a senha padrão '1' (comando: passwd) antes de usar com terceiros.
""")


if __name__ == "__main__":
    main()
