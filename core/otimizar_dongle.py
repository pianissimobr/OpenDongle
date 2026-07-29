#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
otimizar_dongle.py — Otimização MASTER do dongle (durabilidade + velocidade)
=============================================================================
Roda NO PC e aplica via SSH num dongle MSM8916 recém-instalado (Debian
do OpenStick). Foco, nesta ordem de prioridade para um servidor 24/7 de
~382MB de RAM e eMMC barato:

  1. DURABILIDADE (proteger o eMMC — é o que mata o aparelho):
     - logs em RAM (journald volátil, tamanho limitado)
     - noatime/commit no rootfs (menos escrita a cada leitura)
     - reduzir escrita de sistema (motd dinâmico, man-db, apt timers)
  2. VELOCIDADE / MEMÓRIA:
     - zram (swap comprimido na RAM) dimensionado para 382MB
     - sysctl calibrado para zram (swappiness alto é BOM com zram)
     - desligar serviços inúteis num dongle headless (libera RAM)
  3. RESILIÊNCIA:
     - earlyoom (mata o processo certo antes do sistema travar)

Tudo é IDEMPOTENTE (rodar 2x não duplica nada) e REVERSÍVEL (cada
mudança some com --reverter). Mede free/df ANTES e DEPOIS.

Uso:
  python3 otimizar_dongle.py                 # aplica tudo
  python3 otimizar_dongle.py --dry-run       # só mostra o que faria
  python3 otimizar_dongle.py --reverter      # desfaz o que este script fez
  python3 otimizar_dongle.py --ip 192.168.100.1 --senha 1
"""

import argparse
import shutil
import subprocess
import sys

IP = "192.168.100.1"
USUARIO = "user"
SENHA = "1"
TAG = "# TARSILA-OPT"   # marca nossas linhas para idempotência/reversão


# ------------------------------------------------------------- SSH helpers
SSH_BASE = ["-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=10",
            "-o", "LogLevel=ERROR"]

_CHAVE_OK = None


def _tem_chave(ip):
    """Testa uma vez (rápido, BatchMode) se a chave SSH já autentica.
    Qualquer falha (ssh ausente, timeout, rede) → assume que não há chave,
    sem quebrar o script."""
    global _CHAVE_OK
    if _CHAVE_OK is None:
        try:
            r = subprocess.run(
                ["ssh", "-o", "BatchMode=yes"] + SSH_BASE +
                [f"{USUARIO}@{ip}", "true"],
                capture_output=True, timeout=15)
            _CHAVE_OK = (r.returncode == 0)
        except Exception:
            _CHAVE_OK = False
    return _CHAVE_OK


def ssh_prefix(senha, ip=None):
    """
    Monta o prefixo SSH robusto para rede de bancada:
      - se a chave SSH já autentica (instalada pelo orquestrador), usa-a;
      - senão, se houver sshpass, passa a senha;
      - sempre com opções que ignoram known_hosts (reflash no mesmo IP).
    """
    ip = ip or IP
    if _tem_chave(ip):
        return ["ssh"] + SSH_BASE
    if shutil.which("sshpass"):
        return ["sshpass", "-p", senha, "ssh"] + SSH_BASE
    # Sem chave e sem sshpass: ainda tentamos (pode ter ssh-agent/askpass).
    return ["ssh"] + SSH_BASE


def remoto(senha, ip, comando, sudo=False):
    """Roda um comando no dongle. sudo=True usa 'sudo -S' com a senha."""
    ssh = ssh_prefix(senha)
    if sudo:
        comando = f"sudo -S bash -c {shell_quote(comando)}"
        r = subprocess.run(ssh + [f"{USUARIO}@{ip}", comando],
                           input=(senha + "\n").encode(),
                           capture_output=True)
    else:
        r = subprocess.run(ssh + [f"{USUARIO}@{ip}", comando],
                           capture_output=True)
    return (r.returncode,
            r.stdout.decode(errors="replace"),
            r.stderr.decode(errors="replace"))


def shell_quote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def diag(senha, ip):
    """Retorna free -h e df -h / como texto, para o antes/depois."""
    _, out, _ = remoto(senha, ip,
                       "free -h; echo '---'; df -h / | tail -1; "
                       "echo '---'; nproc")
    return out


# ------------------------------------------------------------- as etapas
# Cada etapa: (nome, comando_bash_aplicar, comando_bash_reverter)
# Os comandos rodam como ROOT no dongle e são idempotentes.

def montar_etapas():
    etapas = []

    # 1. journald em RAM (volátil) — logs param de bater no eMMC
    etapas.append((
        "Logs em RAM (journald volátil, 32M)",
        # cria um drop-in; volatile = só RAM, cap de tamanho pequeno
        "mkdir -p /etc/systemd/journald.conf.d && "
        "printf '%s\\n[Journal]\\nStorage=volatile\\n"
        "RuntimeMaxUse=32M\\nSystemMaxUse=32M\\n' "
        f"'{TAG}' > /etc/systemd/journald.conf.d/tarsila.conf && "
        "systemctl restart systemd-journald",
        "rm -f /etc/systemd/journald.conf.d/tarsila.conf && "
        "systemctl restart systemd-journald",
    ))

    # 2. noatime + commit=60 no rootfs — menos escrita por leitura
    #    Edita /etc/fstab de forma reversível (marca a linha alterada).
    etapas.append((
        "Rootfs noatime,commit=60 (menos escrita no eMMC)",
        # backup do fstab uma vez; adiciona noatime,commit se ainda não tem
        "cp -n /etc/fstab /etc/fstab.tarsila.bak; "
        "awk '$2==\"/\"&&$0!~/noatime/{sub($4,$4\",noatime,commit=60\")} "
        "{print}' /etc/fstab.tarsila.bak > /etc/fstab && "
        f"echo '{TAG} fstab modificado' >> /etc/fstab; "
        "mount -o remount / 2>/dev/null || true",
        "test -f /etc/fstab.tarsila.bak && "
        "mv /etc/fstab.tarsila.bak /etc/fstab; "
        "mount -o remount / 2>/dev/null || true",
    ))

    # 3. zram — swap comprimido na RAM. Em 382MB com quad-core ocioso,
    #    trocamos CPU (abundante) por RAM efetiva (escassa): PERCENT=150.
    #    ~573MB de swap comprimido; com zstd (~2.5:1) custa ~230MB de RAM
    #    física quando cheio, e o earlyoom (etapa 5) é a rede de segurança
    #    contra thrashing. zram-tools é o pacote Debian.
    etapas.append((
        "zram (swap comprimido, 150% da RAM — CPU sobra, RAM falta)",
        "DEBIAN_FRONTEND=noninteractive apt-get install -y zram-tools "
        ">/dev/null 2>&1; "
        "printf 'ALGO=zstd\\nPERCENT=150\\nPRIORITY=100\\n%s\\n' "
        f"'{TAG}' > /etc/default/zramswap && "
        "systemctl restart zramswap 2>/dev/null || "
        "systemctl restart zram-tools 2>/dev/null || true",
        "systemctl stop zramswap 2>/dev/null; "
        "apt-get purge -y zram-tools >/dev/null 2>&1 || true",
    ))

    # 4. sysctl calibrado para zram (swappiness ALTO é bom: swap é RAM)
    etapas.append((
        "sysctl para zram (swappiness=100, dirty ratios baixos)",
        "printf '%s\\nvm.swappiness=100\\n"
        "vm.vfs_cache_pressure=50\\n"
        "vm.dirty_background_ratio=5\\n"
        "vm.dirty_ratio=10\\n' "
        f"'{TAG}' > /etc/sysctl.d/99-tarsila.conf && "
        "sysctl -p /etc/sysctl.d/99-tarsila.conf >/dev/null",
        "rm -f /etc/sysctl.d/99-tarsila.conf",
    ))

    # 5. earlyoom — em vez de o sistema congelar sob pressão de RAM,
    #    mata o maior vilão e segue vivo. Essencial em 382MB.
    etapas.append((
        "earlyoom (mata processo certo antes de travar)",
        "DEBIAN_FRONTEND=noninteractive apt-get install -y earlyoom "
        ">/dev/null 2>&1 && "
        "systemctl enable --now earlyoom >/dev/null 2>&1 || true",
        "systemctl disable --now earlyoom >/dev/null 2>&1; "
        "apt-get purge -y earlyoom >/dev/null 2>&1 || true",
    ))

    # 6. Desligar serviços inúteis num dongle headless (libera RAM/escrita).
    #    Cada um é mascarado (reversível com unmask). Só mexe se existir.
    inuteis = ["ModemManager", "bluetooth", "cups", "cups-browsed",
               "avahi-daemon", "man-db.timer", "apt-daily.timer",
               "apt-daily-upgrade.timer", "e2scrub_all.timer"]
    # OBS: ModemManager é desligado por padrão porque estes dongles servem
    # como REDE USB/servidor. Se for usar o 4G, veja --manter-4g.
    aplicar = "; ".join(
        f"systemctl disable --now {s} 2>/dev/null; "
        f"systemctl mask {s} 2>/dev/null" for s in inuteis) + "; true"
    reverter = "; ".join(
        f"systemctl unmask {s} 2>/dev/null" for s in inuteis) + "; true"
    etapas.append(("Desligar serviços inúteis (headless)", aplicar, reverter))

    # 7. Higiene de escrita: motd dinâmico e man-db custam I/O à toa
    etapas.append((
        "Desligar motd dinâmico e indexação man-db",
        "systemctl mask motd-news.timer 2>/dev/null; "
        "chmod -x /etc/update-motd.d/* 2>/dev/null; true",
        "systemctl unmask motd-news.timer 2>/dev/null; "
        "chmod +x /etc/update-motd.d/* 2>/dev/null; true",
    ))

    return etapas


# ------------------------------------------------------------- fluxo
def main():
    ap = argparse.ArgumentParser(description="Otimizador master do dongle")
    ap.add_argument("--ip", default=IP)
    ap.add_argument("--senha", default=SENHA)
    ap.add_argument("--dry-run", action="store_true",
                    help="mostra o que faria, sem aplicar")
    ap.add_argument("--reverter", action="store_true",
                    help="desfaz tudo que este script aplicou")
    ap.add_argument("--manter-4g", action="store_true",
                    help="NÃO desliga o ModemManager (se for usar o 4G)")
    args = ap.parse_args()

    # sanidade de conexão
    rc, out, err = remoto(args.senha, args.ip, "echo ok")
    if "ok" not in out:
        sys.exit(f"Não conectei em {args.ip} via SSH. Dongle plugado e "
                 f"rede 'linux' conectada?\n{err[:200]}")

    etapas = montar_etapas()
    if args.manter_4g:
        etapas = [e for e in etapas
                  if "serviços inúteis" not in e[0]] + [
            ("Desligar inúteis (mantendo 4G)",
             etapas[5][1].replace("ModemManager 2>/dev/null; "
                                  "systemctl mask ModemManager 2>/dev/null",
                                  "true"),
             etapas[5][2])]

    if args.dry_run:
        print("== DRY-RUN — nada será aplicado ==\n")
        for nome, aplicar, _ in etapas:
            print(f"● {nome}\n    {aplicar[:160]}...\n")
        return

    print("== ESTADO ANTES ==")
    antes = diag(args.senha, args.ip)
    print(antes)

    idx = 2 if args.reverter else 1   # posição do comando (aplicar/reverter)
    acao = "REVERTENDO" if args.reverter else "APLICANDO"
    print(f"\n== {acao} otimizações ==")
    for nome, *cmds in etapas:
        cmd = cmds[idx - 1]
        print(f"  ● {nome} ...", end=" ", flush=True)
        rc, out, err = remoto(args.senha, args.ip, cmd, sudo=True)
        print("ok" if rc == 0 else f"aviso (rc={rc})")
        if rc != 0 and err.strip():
            print("      " + err.strip().splitlines()[-1][:120])

    print("\n== ESTADO DEPOIS ==")
    depois = diag(args.senha, args.ip)
    print(depois)

    if not args.reverter:
        print("\n>>> Otimização aplicada. Recomendo um reboot para tudo "
              "assentar:")
        print(f"    sshpass -p {args.senha} ssh {USUARIO}@{args.ip} "
              "'sudo reboot'")
        print(">>> Para desfazer tudo: python3 otimizar_dongle.py --reverter")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompido.")
