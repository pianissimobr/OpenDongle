#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
restaurar_calibracao_ssh.py — Restaura a calibração do modem DE DENTRO do
Debian já instalado, via SSH, com verificação byte a byte. Automatiza o que
tentamos manualmente (e que o copiar/colar embaralhou):

  1. Lê a identidade do dongle (sec/fsg) e acha o backup DELE — nunca "o
     mais recente": o EFS de outro aparelho clona ou zera o IMEI
  2. Salva as partições atuais do dongle antes de mexer (para desfazer)
  3. Envia os .bin, PARA o modem e o rmtfs, desmonta o que estiver montado
     e só então grava cada partição (dd) e VERIFICA com cmp
  4. Reinicia o dongle e confere o IMEI que o modem informa

Por que parar o modem e o rmtfs: o rmtfs guarda o EFS em memória e o
devolve para modemst1/2 quando o modem sincroniza — gravar por baixo dele
é ver a gravação desfeita (ou misturada). E persist/modem ficam montados
pelo msm-firmware-loader: gravar a imagem crua por baixo de um sistema de
arquivos montado corrompe os dois.

Uso (dongle conectado como rede USB):
  python3 restaurar_calibracao_ssh.py
  python3 restaurar_calibracao_ssh.py --senha MINHASENHA   # se mudou a senha
  python3 restaurar_calibracao_ssh.py --pasta backup/dongle_XXXX
  python3 restaurar_calibracao_ssh.py --sem-modemst   # mantém o EFS atual

Dica: instale 'sshpass' (sudo apt install sshpass) para não digitar a
senha várias vezes. Sem ele, o script pede a senha a cada conexão.
"""

import argparse
import datetime
import hashlib
import os
import subprocess
import sys
import shutil
import socket
import tarfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))
from opendongle_autoinstall import (  # noqa: E402
    BACKUP_DIR, PARTICOES_IDENTIDADE, escolher_backup, imei_valido,
    ler_imei_ssh,
)

BASE = Path(__file__).resolve().parent
WORK = BASE / "work"
PARTICOES = ["fsc", "fsg", "modem", "modemst1", "modemst2", "persist", "sec"]
IP = "192.168.100.1"
USUARIO = "user"
SSH_OPTS = ["-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=10"]
# o remoteproc do modem (MSS) no MSM8916; o outro (a204000) é o Wi-Fi
REMOTEPROC_MODEM = "4080000.remoteproc"


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


def como_root(SSH, alvo, senha, script, **kw):
    """Roda um script sh como root no dongle (sudo -S lê a senha do stdin)."""
    return subprocess.run(SSH + [alvo, "sudo -S -p '' sh -c " + _aspas(script)],
                          input=(senha + "\n").encode(), capture_output=True, **kw)


def _aspas(s):
    return "'" + s.replace("'", "'\"'\"'") + "'"


def identidade_dongle(SSH, alvo, senha):
    """sha256 de sec e fsg lidos do próprio dongle."""
    script = "; ".join(f"echo {p} $(sha256sum < /dev/disk/by-partlabel/{p} | cut -d' ' -f1)"
                       for p in PARTICOES_IDENTIDADE)
    r = como_root(SSH, alvo, senha, script, timeout=120)
    ident = {}
    for linha in r.stdout.decode(errors="replace").splitlines():
        partes = linha.split()
        if len(partes) == 2 and partes[0] in PARTICOES_IDENTIDADE and len(partes[1]) == 64:
            ident[partes[0]] = partes[1]
    if set(ident) != set(PARTICOES_IDENTIDADE):
        sys.exit("ABORTADO: não consegui ler sec/fsg do dongle para saber "
                 "qual backup é dele.\n" + r.stderr.decode(errors="replace")[-300:])
    return ident


def salvar_atuais(SSH, alvo, senha, particoes, destino):
    """Copia as partições atuais do dongle para o PC, com sha256."""
    destino.mkdir(parents=True)
    linhas = []
    for p in particoes:
        arq = destino / f"{p}.bin"
        with open(arq, "wb") as f:
            r = subprocess.run(SSH + [alvo, f"sudo -S -p '' cat /dev/disk/by-partlabel/{p}"],
                               input=(senha + "\n").encode(), stdout=f,
                               stderr=subprocess.PIPE)
        if r.returncode != 0 or arq.stat().st_size == 0:
            sys.exit(f"ABORTADO: não consegui salvar a partição atual '{p}'. "
                     "NADA foi gravado no dongle.")
        linhas.append(f"{hashlib.sha256(arq.read_bytes()).hexdigest()}  {p}.bin")
    (destino / "SHA256SUMS").write_text("\n".join(linhas) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pasta", help="pasta do backup (padrão: o backup deste dongle)")
    ap.add_argument("--senha", default="1",
                    help="senha do usuário 'user' no dongle (padrão: 1)")
    ap.add_argument("--ip", default=IP)
    ap.add_argument("--sem-modemst", action="store_true",
                    help="não grava modemst1/modemst2 (mantém o EFS que o "
                         "modem usa hoje; o resto da calibração é gravado)")
    args = ap.parse_args()
    ip = args.ip
    alvo = f"{USUARIO}@{ip}"
    SSH = ssh_base(args.senha)
    particoes = [p for p in PARTICOES
                 if not (args.sem_modemst and p in ("modemst1", "modemst2"))]

    if not porta_aberta(ip):
        sys.exit(f"ABORTADO: {ip}:22 não responde. O dongle está plugado e "
                 "a rede USB 'linux' conectada?")

    # ---- 1. de quem é este dongle? ------------------------------------
    print("== [1/5] Lendo a identidade do dongle (sec/fsg)...")
    ident = identidade_dongle(SSH, alvo, args.senha)
    pasta = escolher_backup(args.pasta, ident)
    print(f"   backup deste dongle: {pasta}")
    faltando = [p for p in particoes if not (pasta / f"{p}.bin").exists()]
    if faltando:
        sys.exit(f"ABORTADO: faltam no backup: {faltando}")
    imei_antes = ler_imei_ssh(ip, USUARIO, args.senha, tentativas=1)
    print(f"   IMEI agora: {imei_antes or 'não lido'}")

    # ---- 2. guarda o estado atual -------------------------------------
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    antes = BACKUP_DIR / f"antes_restauro_{stamp}"
    print(f"== [2/5] Salvando as partições atuais em {antes} ...")
    salvar_atuais(SSH, alvo, args.senha, PARTICOES, antes)
    print("   salvas (para desfazer: --pasta " + str(antes) + ").")

    # ---- 3. empacota e envia numa conexão só --------------------------
    print("== [3/5] Enviando arquivos de calibração para o dongle...")
    WORK.mkdir(exist_ok=True)
    tar_path = WORK / "calibracao.tar"
    with tarfile.open(tar_path, "w") as t:
        for p in particoes:
            t.add(pasta / f"{p}.bin", arcname=f"{p}.bin")
    with open(tar_path, "rb") as f:
        r = subprocess.run(SSH + [alvo, "mkdir -p /tmp/calibracao && "
                                        "tar xf - -C /tmp/calibracao"], stdin=f)
    if r.returncode != 0:
        sys.exit("ABORTADO: envio falhou (senha errada? rede caiu?).")
    print("   enviados.")

    # ---- 4. para o modem, desmonta, grava e VERIFICA ------------------
    print("== [4/5] Parando o modem, gravando e verificando byte a byte...")
    # Qualquer falha antes do primeiro dd sai sem ter gravado nada. Se uma
    # gravação falhar no meio, o exit code sobe e abortamos ANTES do reboot.
    lista = " ".join(particoes)
    script = (
        "set -e; cd /tmp/calibracao; "
        f"for n in {lista}; do test -e /dev/disk/by-partlabel/$n "
        "|| { echo PARTICAO $n AUSENTE; exit 1; }; done; "
        "for r in /sys/class/remoteproc/remoteproc*; do "
        f"  [ \"$(cat $r/name)\" = {REMOTEPROC_MODEM} ] || continue; "
        "  [ \"$(cat $r/state)\" = offline ] || echo stop > $r/state; done; "
        "systemctl stop rmtfs; "
        f"for n in {lista}; do "
        "  dev=$(readlink -f /dev/disk/by-partlabel/$n); "
        "  for m in $(findmnt -rn -S $dev -o TARGET); do "
        "    umount $m || { echo NAO DESMONTOU $m; exit 1; }; done; done; "
        f"for n in {lista}; do "
        '  echo "== $n =="; '
        "  dd if=$n.bin of=/dev/disk/by-partlabel/$n bs=1M conv=fsync status=none; "
        "  s=$(stat -c%s $n.bin); "
        "  cmp -n $s $n.bin /dev/disk/by-partlabel/$n "
        '    && echo "   VERIFICADO ($s bytes)" '
        '    || { echo "   FALHA NA VERIFICACAO de $n"; exit 1; }; '
        "done; sync; cd /; rm -rf /tmp/calibracao; echo TUDO_OK"
    )
    r = como_root(SSH, alvo, args.senha, script)
    saida = r.stdout.decode(errors="replace")
    print(saida)
    if r.returncode != 0 or "TUDO_OK" not in saida:
        print(r.stderr.decode(errors="replace")[-500:])
        sys.exit("ABORTADO: gravação/verificação falhou. NADA de reboot — "
                 "me mande a saída acima. As partições de antes estão em "
                 f"{antes}. O modem pode ter ficado parado: reinicie o "
                 "dongle quando terminar de olhar.")

    # ---- 5. reboot, espera voltar e confere o IMEI --------------------
    print("== [5/5] Calibração gravada e verificada. Reiniciando o dongle...")
    como_root(SSH, alvo, args.senha, "systemctl reboot")
    time.sleep(10)
    print("   aguardando o dongle voltar (até 4 min; o boot pós-reboot "
          "é bem mais rápido que o primeiro)...")
    inicio = time.time()
    while time.time() - inicio < 240:
        if porta_aberta(ip):
            break
        time.sleep(5)
    else:
        sys.exit("Dongle não voltou em 4 min. Replugue e confira o IMEI: "
                 f"ssh {alvo} 'mmcli -m any | grep -i imei'.")
    print("   de volta! Lendo o IMEI (o modem leva até ~1 min)...")
    imei = ler_imei_ssh(ip, USUARIO, args.senha)
    if imei is None:
        print(">>> Não consegui ler o IMEI (precisa de sshpass e do mmcli ou "
              "qmicli no dongle). Confira à mão: "
              f"ssh {alvo} 'mmcli -m any | grep -i imei'")
    elif imei_valido(imei):
        print(f">>> MODEM OK: IMEI {imei}. Com chip SIM, o 4G registra em instantes.")
    else:
        print(f">>> ATENÇÃO: o modem agora responde IMEI {imei}: ele NÃO aceitou "
              "o EFS deste backup.\n"
              ">>> Volte o que havia antes com:\n"
              f"      python3 {Path(__file__).name} --pasta {antes}\n"
              ">>> ou mantenha o EFS atual e grave só o resto: --sem-modemst")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompido — nenhuma alteração parcial foi rebootada.")
