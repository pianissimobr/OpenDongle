#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
restaurar_calibracao_ssh.py — Restaura a calibração do modem DE DENTRO do
Debian já instalado, via SSH, com verificação byte a byte. Automatiza o que
tentamos manualmente (e que o copiar/colar embaralhou):

  1. Envia os 7 .bin do backup para /tmp do dongle (uma conexão só, via tar)
  2. Grava cada um na partição certa (dd) e VERIFICA com cmp
  3. Reinicia o dongle e espera voltar
  4. Testa o modem (mmcli/nmcli) e mostra o resultado

Uso (na pasta openstick-auto, dongle conectado como rede USB):
  python3 restaurar_calibracao_ssh.py
  python3 restaurar_calibracao_ssh.py --senha MINHASENHA   # se mudou a senha
  python3 restaurar_calibracao_ssh.py --pasta backup/dongle_XXXX

Dica: instale 'sshpass' (sudo apt install sshpass) para não digitar a
senha várias vezes. Sem ele, o script pede a senha a cada conexão.
"""

import argparse
import subprocess
import sys
import shutil
import socket
import tarfile
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
BACKUP_DIR = BASE / "backup"
WORK = BASE / "work"
PARTICOES = ["fsc", "fsg", "modem", "modemst1", "modemst2", "persist", "sec"]
IP = "192.168.100.1"
USUARIO = "user"
SSH_OPTS = ["-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=10"]


def ssh_base(senha):
    """Prefixa com sshpass se disponível (evita digitar senha toda hora)."""
    if shutil.which("sshpass"):
        return ["sshpass", "-p", senha, "ssh"] + SSH_OPTS
    print("(sem sshpass — a senha SSH será pedida em cada etapa)")
    return ["ssh"] + SSH_OPTS


def porta_aberta(ip, porta=22, timeout=2):
    try:
        with socket.create_connection((ip, porta), timeout=timeout):
            return True
    except OSError:
        return False


def achar_pasta(arg):
    if arg:
        p = Path(arg)
        if not p.is_dir():
            sys.exit(f"Pasta não existe: {p}")
        return p
    pastas = sorted(p for p in BACKUP_DIR.glob("dongle_*")
                    if (p / "manifesto.json").exists())
    if not pastas:
        sys.exit("Nenhum backup verificado em ./backup")
    return pastas[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pasta", help="pasta do backup (padrão: mais recente)")
    ap.add_argument("--senha", default="1",
                    help="senha do usuário 'user' no dongle (padrão: 1)")
    ap.add_argument("--ip", default=IP)
    args = ap.parse_args()
    ip = args.ip
    SSH = ssh_base(args.senha)

    pasta = achar_pasta(args.pasta)
    print(f"== Backup: {pasta}")
    faltando = [p for p in PARTICOES if not (pasta / f"{p}.bin").exists()]
    if faltando:
        sys.exit(f"ABORTADO: faltam no backup: {faltando}")

    if not porta_aberta(ip):
        sys.exit(f"ABORTADO: {ip}:22 não responde. O dongle está plugado e "
                 "a rede USB 'linux' conectada?")

    # ---- 1. empacota e envia numa conexão só --------------------------
    print("== [1/4] Enviando arquivos de calibração para o dongle...")
    WORK.mkdir(exist_ok=True)
    tar_path = WORK / "calibracao.tar"
    with tarfile.open(tar_path, "w") as t:
        for p in PARTICOES:
            t.add(pasta / f"{p}.bin", arcname=f"{p}.bin")
    with open(tar_path, "rb") as f:
        r = subprocess.run(SSH + [f"{USUARIO}@{ip}", "tar xf - -C /tmp"],
                           stdin=f)
    if r.returncode != 0:
        sys.exit("ABORTADO: envio falhou (senha errada? rede caiu?).")
    print("   enviados.")

    # ---- 2. grava com dd e VERIFICA com cmp ---------------------------
    print("== [2/4] Gravando nas partições e verificando byte a byte...")
    # sudo -S lê a senha do stdin; o script remoto valida cada gravação
    # comparando a partição com o arquivo (cmp). Se qualquer uma diferir,
    # o exit code sobe e abortamos ANTES do reboot.
    lista = " ".join(PARTICOES)
    remoto = (
        "sudo -S bash -c '"
        "set -e; "
        f"for n in {lista}; do "
        '  echo \"== $n ==\"; '
        "  test -e /dev/disk/by-partlabel/$n || { echo PARTICAO $n AUSENTE; exit 1; }; "
        "  dd if=/tmp/$n.bin of=/dev/disk/by-partlabel/$n bs=1M conv=fsync status=none; "
        "  s=$(stat -c%s /tmp/$n.bin); "
        "  cmp -n $s /tmp/$n.bin /dev/disk/by-partlabel/$n "
        "    && echo \"   VERIFICADO ($s bytes)\" "
        "    || { echo \"   FALHA NA VERIFICACAO de $n\"; exit 1; }; "
        "done; sync; echo TUDO_OK'"
    )
    r = subprocess.run(SSH + [f"{USUARIO}@{ip}", remoto],
                       input=(args.senha + "\n").encode(),
                       capture_output=True)
    saida = r.stdout.decode(errors="replace")
    print(saida)
    if r.returncode != 0 or "TUDO_OK" not in saida:
        print(r.stderr.decode(errors="replace")[-500:])
        sys.exit("ABORTADO: gravação/verificação falhou. NADA de reboot — "
                 "me mande a saída acima.")

    # ---- 3. reboot e espera voltar -------------------------------------
    print("== [3/4] Calibração gravada e verificada. Reiniciando o dongle...")
    subprocess.run(SSH + [f"{USUARIO}@{ip}", "sudo -S reboot"],
                   input=(args.senha + "\n").encode(), capture_output=True)
    time.sleep(10)
    print("   aguardando o dongle voltar (até 4 min; o boot pós-reboot "
          "é bem mais rápido que o primeiro)...")
    inicio = time.time()
    while time.time() - inicio < 240:
        if porta_aberta(ip):
            break
        time.sleep(5)
    else:
        sys.exit("Dongle não voltou em 4 min. Replugue e rode: "
                 f"ssh {USUARIO}@{ip} 'mmcli -L' para testar o modem.")
    print("   de volta!")

    # ---- 4. teste do modem ---------------------------------------------
    print("== [4/4] Testando o modem (precisa de chip SIM inserido)...")
    time.sleep(15)   # dá tempo do ModemManager enumerar o modem
    r = subprocess.run(SSH + [f"{USUARIO}@{ip}",
                              "mmcli -L; echo ---; nmcli device status"],
                       capture_output=True)
    print(r.stdout.decode(errors="replace"))
    saida = r.stdout.decode(errors="replace")
    if "/Modem/" in saida:
        print(">>> MODEM DETECTADO! Se o chip estiver dentro, o 4G deve "
              "registrar na operadora em instantes.")
        print(">>> Detalhes: ssh no dongle e rode 'mmcli -m 0'")
    else:
        print(">>> Modem ainda não listado. Possíveis causas: sem chip SIM, "
              "ou o firmware do modem demora ~1 min no primeiro boot pós-"
              f"calibração. Aguarde e rode: ssh {USUARIO}@{ip} 'mmcli -L'")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompido — nenhuma alteração parcial foi rebootada.")
