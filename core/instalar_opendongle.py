#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
instalar_opendongle.py — instala o painel OpenDongle no dongle (roda no PC)
============================================================================
Coloca no dongle, via SSH:
  - motor único + CLI + painel web (em /opt/opendongle)
  - comando `opendongle` em /usr/local/bin (a CLI)
  - um serviço systemd só (opendongle.service -> opendongled.py), com o
    painel web (porta 80), o uplink guard (gateway condicional), os LEDs
    (papel USB, modo Wi-Fi, internet, áudio) e a descoberta na rede
    (responde probe UDP pra ferramentas/opendongle_localizar.py) como
    threads do mesmo processo Python — economiza RAM
  - usb-role-autosense.sh (grupos, Bluetooth, papel USB, 4G plug-and-play)
  - módulos do Bluetooth e LED triggers carregados em todo boot, e o
    bluetooth.service (bluetoothd) desmascarado e ativo
  - config central em /etc/opendongle/config.json (migra SSID/senha/APNs
    atuais) aplicada: dnsmasq, firewall nftables, ip_forward e APN
  - rede sem NetworkManager: systemd-networkd + hostapd (hotspot) ou
    wpa_supplicant (cliente), com reversão automática se o acesso cair
  - avahi configurado para responder opendongle.local
  - garante o SSID/senha padrão do hotspot: OpenDongle / opendongle
  - reinicia o dongle no final, pra ativar o usb-role-autosense de vez
    (ele só decide o papel USB corretamente longe de uma instalação SSH
    em andamento — ver nota no [2/7])
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
        "opendongle_discovery.py", "opendongle_config.py",
        "opendongle_apply.py", "opendongled.py", "usb-role-autosense.sh"]

# Um processo só pra painel, uplink guard, LEDs e descoberta (opendongled).
# NÃO ordenar com "After=usb-role-autosense.service": esse serviço tem
# "After=multi-user.target" (proposital — ver UNIT_USBROLE), e como este é
# WantedBy=multi-user.target (Before= implícito), fecha um ciclo de
# dependência que o systemd resolve descartando o job em todo boot (visto
# ao vivo com o antigo opendongle-led.service). Os laços fazem polling e se
# corrigem sozinhos, não precisam de ordem estrita de boot.
UNIT = """[Unit]
Description=OpenDongle (painel web, uplink guard, LEDs e descoberta)
After=network.target NetworkManager.service

[Service]
ExecStart=/usr/bin/python3 /opt/opendongle/opendongled.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""

# Units de versões antigas, quando cada parte era um processo separado.
UNITS_ANTIGAS = ["opendongle-uplink.service", "opendongle-led.service",
                 "opendongle-discovery.service"]

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

# Vêm no kernel msm8916 como módulo mas nada os carrega sozinho: perfis BT
# (rfcomm/hidp/bnep), drivers de adaptador BT USB e os LED triggers extras.
MODULOS_BT = ["btqcomsmd", "btqca", "btusb", "btintel", "btrtl", "btbcm",
              "rfcomm", "hidp", "bnep"]
MODULOS_LEDTRIG = ["ledtrig-activity", "ledtrig-backlight", "ledtrig-camera",
                   "ledtrig-gpio", "ledtrig-netdev", "ledtrig-oneshot",
                   "ledtrig-pattern", "ledtrig-transient", "ledtrig-tty"]
MODULES_LOAD = "\n".join(MODULOS_BT + MODULOS_LEDTRIG) + "\n"

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

    print("== [1/7] Enviando arquivos do painel...")
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

    print("== [2/7] Instalando motor, CLI e serviços (sudo)...")
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
        # NAT e redirecionamento de DNS agora vêm do firewall gerado pela
        # config central (nftables); as regras de iptables da imagem saem.
        "if [ -f \"$ni\" ] && grep -Eq \"^[[:space:]]*up[[:space:]]+ip6*tables \" \"$ni\"; then "
        "cp -n \"$ni\" \"$ni.opendongle.orig\"; "
        "sed -i -E \"/^[[:space:]]*up[[:space:]]+ip6*tables /d\" \"$ni\"; "
        "echo \"iptables do /etc/network/interfaces movido pro firewall da config central\"; "
        "fi && "
        # CLI acessível como 'opendongle'
        "printf \"#!/bin/sh\\nexec /usr/bin/python3 "
        "/opt/opendongle/opendongle_cli.py \\\"\\$@\\\"\\n\" "
        "> /usr/local/bin/opendongle && chmod 755 /usr/local/bin/opendongle && "
        # serviço web
        "cat > /etc/systemd/system/opendongle.service << \"EOF\"\n"
        + UNIT +
        "EOF\n"
        "cat > /etc/systemd/system/usb-role-autosense.service << \"EOF\"\n"
        + UNIT_USBROLE +
        "EOF\n"
        "systemctl disable --now " + " ".join(UNITS_ANTIGAS) + " >/dev/null 2>&1; "
        "rm -f " + " ".join(f"/etc/systemd/system/{u}" for u in UNITS_ANTIGAS) + "\n"
        "cat > /etc/modules-load.d/opendongle.conf << \"EOF\"\n"
        + MODULES_LOAD +
        "EOF\n"
        "modprobe -a " + " ".join(MODULOS_BT + MODULOS_LEDTRIG) +
        " || echo \"aviso: algum modulo do Bluetooth/LED nao carregou\"\n"
        # versões antigas do otimizar_dongle.py mascaravam o bluetooth.service;
        # sem o bluetoothd, o bluetoothctl do painel não funciona. Não é fatal:
        # sem bluez ainda, o usb-role-autosense instala no próximo boot.
        "systemctl unmask bluetooth.service >/dev/null 2>&1; "
        "systemctl enable --now bluetooth.service >/dev/null 2>&1 "
        "|| echo \"aviso: bluetooth.service nao ativou (bluez ausente?)\"\n"
        # config central: na 1a vez migra SSID/senha/APNs atuais e gera
        # dnsmasq, firewall (nftables), ip_forward e APN
        # rede sem NetworkManager (etapa [5/7]) precisa de hostapd e iw;
        # sem internet agora, a instalação segue no NetworkManager
        "DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "
        "hostapd iw >/dev/null 2>&1 && apt-get clean "
        "|| echo \"aviso: hostapd/iw nao instalados (sem internet?)\"\n"
        # dongle não tem tela: o login no tty1 só ocupa RAM
        "systemctl mask --now getty@tty1.service >/dev/null 2>&1\n"
        "python3 /opt/opendongle/opendongle_cli.py config aplicar "
        "|| echo \"aviso: config central nao aplicou (veja a mensagem acima)\"\n"
        "systemctl daemon-reload && "
        # restart (não só --now): numa reinstalação o serviço já está no ar
        # com o código antigo carregado
        "systemctl enable opendongle.service && "
        "systemctl restart opendongle.service && "
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

    print("== [3/7] Configurando avahi (opendongle.local)...")
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

    print("== [4/7] Trocando o NetworkManager por systemd-networkd + hostapd...")
    # Antes do hotspot padrão: assim a troca de SSID/senha já vai pela config
    # central + hostapd (ativar AP pelo NM logo após modo cliente falhou ao
    # vivo com "supplicant took too long"). A migração agenda sozinha uma
    # reversão em 3 min. Só confirmamos depois
    # de reconectar por SSH: se a rede USB não voltar, o dongle desfaz tudo.
    r = subprocess.run(ssh + ["sudo -S /opt/opendongle/opendongle_cli.py rede migrar"],
                       input=(args.senha + "\n").encode(), capture_output=True,
                       timeout=180)
    saida = (r.stdout.decode(errors="replace").strip()
             or r.stderr.decode(errors="replace").strip())
    print("   " + saida.replace("\n", "\n   ")[:400])
    if r.returncode == 0 and "já usa" not in saida:
        confirmado = False
        prazo = time.time() + 120
        while time.time() < prazo:
            try:
                r = subprocess.run(
                    ssh + ["sudo -S /opt/opendongle/opendongle_cli.py rede confirmar"],
                    input=(args.senha + "\n").encode(), capture_output=True, timeout=20)
                if r.returncode == 0:
                    confirmado = True
                    break
            except subprocess.TimeoutExpired:
                pass
            time.sleep(3)
        print("   ✓ rede nova confirmada" if confirmado else
              "   ⚠ não reconectei pra confirmar: o dongle volta sozinho pro "
              "NetworkManager em até 3 min")
    elif r.returncode != 0:
        print("   ⚠ migração não feita; o dongle segue no NetworkManager")

    print("== [5/7] Garantindo hotspot padrão OpenDongle/opendongle...")
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
  Se nem isso resolver, rode ferramentas/opendongle_localizar.py no PC:
  ele acha o IP do dongle sozinho, sem depender de USB nem do roteador.
- Ao trocar nome/senha do hotspot, os clientes caem e precisam
  reconectar (a página avisa isso ao usuário).
""")

    print("== [6/7] Reiniciando o dongle para ativar o usb-role-autosense...")
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

    print("== [7/7] Esperando o dongle voltar pra rodar o teste geral...")
    def _porta_ssh_aberta():
        try:
            socket.create_connection((args.ip, 22), timeout=3).close()
            return True
        except OSError:
            return False

    # Primeiro espera a porta CAIR: o reboot leva alguns segundos pra começar
    # e, sem isso, as checagens pegavam o sistema antigo no meio do
    # desligamento ("Connection reset by peer" em tudo, visto ao vivo).
    prazo = time.time() + 60
    while time.time() < prazo and _porta_ssh_aberta():
        time.sleep(2)

    # porta aberta não basta: o sshd aceita TCP antes de conseguir autenticar
    voltou = False
    prazo = time.time() + 150
    while time.time() < prazo:
        if _porta_ssh_aberta():
            try:
                if subprocess.run(ssh + ["true"], capture_output=True,
                                  timeout=15).returncode == 0:
                    voltou = True
                    break
            except subprocess.TimeoutExpired:
                pass
        time.sleep(3)

    if not voltou:
        print("   ⚠ SSH não voltou em ~2min. Pode ser boot mais lento — "
              "tente 'sudo opendongle status' manualmente daqui a pouco, "
              "ou veja /var/log/usb-role-autosense.log pelo console serial "
              "se o papel USB não tiver resolvido pra 'device'.")
        sys.exit(1)

    # espera o boot terminar: o usb-role-autosense (oneshot) fica
    # "activating" enquanto decide o papel USB e aparecia como falha
    try:
        subprocess.run(ssh + ["timeout 120 systemctl is-system-running --wait"],
                       capture_output=True, timeout=130)
    except subprocess.TimeoutExpired:
        pass
    print("   dongle respondeu — rodando checagens:")
    checagens = [
        ("serviço OpenDongle (painel, uplink, LEDs, descoberta)",
                                       "systemctl is-active opendongle.service"),
        ("serviço usb-role-autosense", "systemctl is-active usb-role-autosense.service"),
        ("avahi (opendongle.local)",   "systemctl is-active avahi-daemon"),
        ("papel USB (informativo)",    "cat /sys/class/usb_role/ci_hdrc.0-role-switch/role"),
        # /etc/opendongle é 0700 (sem sudo aqui): o NM mascarado é o sinal
        ("rede (informativo)",         "[ \"$(systemctl is-enabled NetworkManager "
                                       "2>/dev/null)\" = masked ] && echo systemd-networkd "
                                       "|| echo NetworkManager"),
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
