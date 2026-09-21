#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backup_radio.py — backup das partições de rádio de um dongle que já roda Debian
================================================================================
Roda no PC (Linux/macOS), com o dongle ligado e acessível por SSH. Guarda o
que torna cada aparelho único e não se recupera de outro: a calibração de
rádio e a identidade do modem (IMEI). Sem isso, um flash errado perde o IMEI
para sempre — foi o que aconteceu com o dongle de teste, que ficou com as 7
partições de rádio zeradas e nenhum backup delas.

Uso:
  python3 ferramentas/backup_radio.py --imei 861766035241425
  python3 ferramentas/backup_radio.py --imei 8617... --host 192.168.100.1 --usuario alan
  python3 ferramentas/backup_radio.py --imei 8617... --emmc-completa   # + eMMC inteiro (~3,9 GB)

O IMEI é o da ETIQUETA do dongle: é por ele que os backups ficam separados,
em backups-radio/<IMEI>/<data-hora>/. O script pede a senha do SSH (se não
houver chave) e a do sudo no dongle. Para automatizar, a senha pode vir da
variável OPENDONGLE_SENHA (com o sshpass instalado, vale para o SSH também).

Cada partição é lida pelo NOME (PARTNAME), não pelo número — a numeração muda
entre revisões de placa —, e conferida com sha256 calculado nos dois lados.
Partição só de zeros é avisada: o backup existe, mas aquele aparelho já perdeu
o que ela guardava.
"""
import argparse
import datetime
import getpass
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "backups-radio"
# as que guardam calibração, identidade (IMEI na EFS) e o firmware do modem
PARTICOES = ["modemst1", "modemst2", "fsg", "fsc", "persist", "modem", "sec"]
# Estas têm que ter conteúdo num aparelho saudável: zeradas = identidade ou
# calibração perdida. O fsc e o sec vêm (quase) zerados de fábrica — visto nos
# dumps originais: fsc 100% zeros, sec 99,7% —, então zero ali não é alarme.
PRECISAM_CONTEUDO = {"modemst1", "modemst2", "fsg", "persist", "modem"}

VERMELHO, AMARELO, VERDE, FIM = "\033[31m", "\033[33m", "\033[32m", "\033[0m"


def luhn_ok(imei):
    soma = 0
    for i, c in enumerate(reversed(imei)):
        n = int(c)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        soma += n
    return soma % 10 == 0


class Dongle:
    """Conexão SSH reaproveitada (ControlMaster): a senha do SSH é pedida uma
    vez só, e cada comando depois vai pelo mesmo canal."""

    def __init__(self, usuario, host, senha_sudo):
        self.alvo = f"{usuario}@{host}"
        self.senha = senha_sudo
        self.pasta = tempfile.mkdtemp(prefix="od-backup-")
        self.sock = os.path.join(self.pasta, "ssh.sock")
        base = ["ssh", "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ConnectTimeout=10", "-S", self.sock]
        cmd = base + ["-M", "-f", "-N", "-o", "ControlPersist=600", self.alvo]
        senha_ssh = os.environ.get("OPENDONGLE_SENHA")
        env = None
        if senha_ssh and shutil.which("sshpass"):
            cmd = ["sshpass", "-e"] + cmd          # o sshpass -e lê a SSHPASS
            env = dict(os.environ, SSHPASS=senha_ssh)
        if subprocess.run(cmd, env=env).returncode != 0:
            sys.exit("Não consegui abrir o SSH com o dongle.")
        self.base = base

    def rodar(self, comando, sudo=False):
        """Roda no dongle. Com sudo, a senha vai pelo stdin (nunca na linha de
        comando, que apareceria no 'ps')."""
        if sudo:
            comando = f"sudo -S -p '' {comando}"
        r = subprocess.run(self.base + [self.alvo, comando],
                           input=(self.senha + "\n").encode() if sudo else None,
                           capture_output=True)
        return r.returncode, r.stdout.decode(errors="replace").strip()

    def fechar(self):
        subprocess.run(self.base + ["-O", "exit", self.alvo], capture_output=True)
        shutil.rmtree(self.pasta, ignore_errors=True)


def mapa_particoes(d):
    """{PARTNAME: /dev/...} lido do sysfs (não precisa de root)."""
    _, saida = d.rodar(
        "for u in /sys/class/block/*/uevent; do "
        "n=$(grep -m1 ^PARTNAME= $u | cut -d= -f2); "
        "[ -n \"$n\" ] && echo \"$n $(grep -m1 ^DEVNAME= $u | cut -d= -f2)\"; done")
    mapa = {}
    for linha in saida.splitlines():
        partes = linha.split()
        if len(partes) == 2:
            mapa[partes[0]] = "/dev/" + partes[1]
    return mapa


def identidade(d):
    """Tudo que ajuda a saber, depois, de qual aparelho veio o backup."""
    def ler(caminho, sudo=False):
        texto = d.rodar(f"cat {caminho} 2>/dev/null", sudo=sudo)[1]
        return "".join(c for c in texto if c.isprintable()).strip()
    _, ids = d.rodar("qmicli -d /dev/wwan0qmi0 --dms-get-ids 2>/dev/null", sudo=True)
    imei_modem = ""
    for linha in ids.splitlines():
        if "IMEI" in linha:
            imei_modem = linha.split("'")[1] if "'" in linha else linha.split(":")[-1].strip()
    return {
        "imei_modem": imei_modem,
        "soc_serial": ler("/sys/devices/soc0/serial_number"),
        "soc_serial_hex": "",
        "emmc_cid": ler("/sys/block/mmcblk0/device/cid"),
        "emmc_nome": ler("/sys/block/mmcblk0/device/name"),
        "opendongle_id": ler("/etc/opendongle/id", sudo=True),   # /etc/opendongle é só do root
        "hostname": d.rodar("hostname")[1],
        "kernel": d.rodar("uname -r")[1],
        "modelo": ler("/sys/firmware/devicetree/base/model"),
    }


def puxar(d, nome, dev, pasta):
    """Lê a partição pelo SSH em fluxo (a eMMC inteira tem 3,9 GB: nada de
    carregar na memória), confere o sha256 nos dois lados e diz se ela é só
    zeros."""
    hash_local, total, algo = hashlib.sha256(), 0, False
    proc = subprocess.Popen(d.base + [d.alvo, f"sudo -S -p '' dd if={dev} bs=1M status=none"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    proc.stdin.write((d.senha + "\n").encode())
    proc.stdin.close()
    with open(pasta / f"{nome}.bin", "wb") as f:
        while bloco := proc.stdout.read(1 << 20):
            f.write(bloco)
            hash_local.update(bloco)
            total += len(bloco)
            algo = algo or any(bloco)
    if proc.wait() != 0 or not total:
        return {"nome": nome, "dev": dev, "erro": "não consegui ler"}
    _, remoto = d.rodar(f"sha256sum {dev}", sudo=True)
    remoto = remoto.split()[0] if remoto else ""
    local = hash_local.hexdigest()
    return {"nome": nome, "dev": dev, "bytes": total, "sha256": local,
            "confere": local == remoto, "zerada": not algo}


def main():
    ap = argparse.ArgumentParser(description="Backup das partições de rádio de um dongle, por IMEI.")
    ap.add_argument("--imei", required=True, help="IMEI da etiqueta do dongle (15 dígitos)")
    ap.add_argument("--host", default="192.168.100.1")
    ap.add_argument("--usuario", default=os.environ.get("OPENDONGLE_USUARIO", "user"))
    ap.add_argument("--emmc-completa", action="store_true",
                    help="também copia o eMMC inteiro (~3,9 GB; leva vários minutos)")
    args = ap.parse_args()

    imei = args.imei.strip().replace(" ", "")
    if not (imei.isdigit() and len(imei) == 15):
        sys.exit("O IMEI tem 15 dígitos (o da etiqueta do dongle).")
    if not luhn_ok(imei):
        resp = input(f"{AMARELO}O dígito verificador do IMEI {imei} não bate — erro de "
                     f"digitação?{FIM} Continuar mesmo assim? [s/N] ")
        if resp.strip().lower() != "s":
            sys.exit(1)

    senha = os.environ.get("OPENDONGLE_SENHA") or getpass.getpass(
        f"Senha do sudo de {args.usuario} no dongle: ")
    d = Dongle(args.usuario, args.host, senha)
    try:
        if d.rodar("true", sudo=True)[0] != 0:
            sys.exit("O sudo recusou a senha.")
        # só depois de conectar: uma falha antes não deixa pasta vazia
        pasta = DESTINO / imei / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        pasta.mkdir(parents=True, exist_ok=False)
        print(f"Backup em {pasta.relative_to(RAIZ)}")
        info = {"imei_etiqueta": imei, "quando": datetime.datetime.now().isoformat(timespec="seconds"),
                **identidade(d)}
        if info["soc_serial"].isdigit():
            info["soc_serial_hex"] = f"0x{int(info['soc_serial']):08x}"
        mapa = mapa_particoes(d)
        info["particoes"] = []
        for nome in PARTICOES:
            if nome not in mapa:
                print(f"  {AMARELO}- {nome}: não existe neste aparelho{FIM}")
                continue
            r = puxar(d, nome, mapa[nome], pasta)
            info["particoes"].append(r)
            if r.get("erro"):
                print(f"  {VERMELHO}✗ {nome}: {r['erro']}{FIM}")
            elif not r["confere"]:
                print(f"  {VERMELHO}✗ {nome}: o sha256 não confere com o do dongle{FIM}")
            elif r["zerada"] and nome in PRECISAM_CONTEUDO:
                print(f"  {VERMELHO}! {nome}: só zeros — este aparelho já perdeu o que ela guardava{FIM}")
            elif r["zerada"]:
                print(f"  {VERDE}✓ {nome}{FIM} (vazia — normal nesta partição)")
            else:
                print(f"  {VERDE}✓ {nome}{FIM} ({r['bytes'] // 1024} KB)")
        if args.emmc_completa:
            print("  eMMC inteira (vários minutos)…")
            r = puxar(d, "emmc_completa", "/dev/mmcblk0", pasta)
            info["particoes"].append(r)
            print(f"  {VERDE if r.get('confere') else VERMELHO}"
                  f"{'✓' if r.get('confere') else '✗'} emmc_completa{FIM}")
        (pasta / "SHA256SUMS").write_text("".join(
            f"{p['sha256']}  {p['nome']}.bin\n" for p in info["particoes"] if p.get("sha256")))
        (pasta / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2))
    finally:
        d.fechar()

    zeradas = [p["nome"] for p in info["particoes"]
               if p.get("zerada") and p["nome"] in PRECISAM_CONTEUDO]
    falhas = [p["nome"] for p in info["particoes"] if p.get("erro") or not p.get("confere", True)]
    print()
    print(f"IMEI da etiqueta: {imei} · IMEI que o modem informa: {info['imei_modem'] or '(nenhum)'}")
    print(f"SoC {info['soc_serial_hex'] or info['soc_serial']} · eMMC {info['emmc_cid']}")
    if info["imei_modem"] and info["imei_modem"] != imei:
        print(f"{AMARELO}O IMEI do modem é diferente do da etiqueta.{FIM}")
    if falhas:
        print(f"{VERMELHO}Falhou: {', '.join(falhas)} — rode de novo.{FIM}")
        sys.exit(1)
    if zeradas:
        print(f"{VERMELHO}Partições zeradas: {', '.join(zeradas)}. O backup está salvo, mas "
              f"NÃO devolve a identidade deste aparelho.{FIM}")
    else:
        print(f"{VERDE}Backup completo e conferido.{FIM} Guarde a pasta fora do PC também.")


if __name__ == "__main__":
    main()
