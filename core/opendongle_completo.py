#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongle_completo.py — Orquestrador MASTER do dongle OpenDongle
==========================================================
Roda a jornada inteira num dongle MSM8916, de ponta a ponta, chamando
os módulos que já construímos e testamos:

  [1] Instalar Debian ............ opendongle_autoinstall.py  (opcional)
  [2] Otimizar (durab.+veloc.) ... otimizar_dongle.py
  [3] Painel OpenDongle .......... instalar_opendongle.py
  [4] Acesso serial USB .......... configurado aqui (pergunta por dongle)

No início pergunta: fluxo COMPLETO (instala Debian + pós) ou SÓ PÓS
(dongle que já tem Debian). Para cada dongle, pergunta se quer manter
ou desligar o acesso serial USB (/dev/ttyACM), que a imagem OpenStick
já traz habilitado.

Este orquestrador NÃO reimplementa nada: ele coordena os scripts que já
existem, então qualquer melhoria neles é herdada automaticamente.

Uso:
  python3 opendongle_completo.py
  python3 opendongle_completo.py --ip 192.168.100.1 --senha 1
  python3 opendongle_completo.py --so-pos          # pula a pergunta, vai ao pós
  python3 opendongle_completo.py --manter-4g       # repassa ao otimizador
"""

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
PY = sys.executable

# Módulos que orquestramos (devem estar na mesma pasta)
MOD_INSTALL = BASE / "opendongle_autoinstall.py"
MOD_OTIM = BASE / "otimizar_dongle.py"
MOD_PORTAL = BASE / "instalar_opendongle.py"

IP = "192.168.100.1"
USUARIO = "user"
SENHA = "1"

# Opções SSH que tornam o fluxo auto-suficiente para uma REDE DE BANCADA:
# - StrictHostKeyChecking=no + UserKnownHostsFile=/dev/null: nunca dá o erro
#   "REMOTE HOST IDENTIFICATION HAS CHANGED" ao reflashar vários dongles no
#   mesmo IP (cada um gera chave nova). Seguro aqui porque é a sua bancada.
SSH_BANCADA = ["-o", "StrictHostKeyChecking=no",
               "-o", "UserKnownHostsFile=/dev/null",
               "-o", "ConnectTimeout=10",
               "-o", "LogLevel=ERROR"]


def preparar_pc(ip, senha):
    """
    Deixa o fluxo 'plugar e rodar' — resolve sozinho os 3 pré-requisitos
    que antes eram manuais:

      1. never-default: impede que o dongle (sem SIM) roube a rota de
         internet do PC durante a instalação de pacotes.
      2. chave SSH: copia a chave pública do PC pro dongle, para as
         próximas conexões não pedirem senha (elimina o sshpass).
      3. known_hosts: usamos opções que ignoram a verificação para o IP
         de bancada (feito nas chamadas SSH, não aqui).
    """
    print("→ Preparando o PC (never-default + chave SSH)...")

    # (1) never-default na conexão ethernet do dongle
    try:
        r = subprocess.run(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE",
                            "connection", "show", "--active"],
                           capture_output=True, text=True, timeout=15)
        alvo = None
        for linha in (r.stdout or "").splitlines():
            p = linha.split(":")
            if len(p) >= 2 and p[1] in ("802-3-ethernet", "ethernet"):
                alvo = p[0]
                break
        if alvo:
            subprocess.run(["nmcli", "connection", "modify", alvo,
                            "ipv4.never-default", "yes",
                            "ipv6.never-default", "yes"],
                           capture_output=True, timeout=15)
            subprocess.run(["nmcli", "connection", "down", alvo],
                           capture_output=True, timeout=15)
            subprocess.run(["nmcli", "connection", "up", alvo],
                           capture_output=True, timeout=20)
            print(f"  ✓ never-default aplicado em '{alvo}' "
                  "(sua internet fica protegida)")
        else:
            print("  · conexão do dongle ainda não visível; sigo mesmo "
                  "assim (o uplink_guard cuidará no dongle).")
    except Exception as e:
        print(f"  · não consegui aplicar never-default automaticamente "
              f"({e}); não é bloqueante.")

    # (2) garante uma chave SSH local e copia pro dongle (1x)
    try:
        chave = Path.home() / ".ssh" / "id_ed25519"
        if not chave.exists():
            subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "",
                            "-f", str(chave)], capture_output=True)
            print("  ✓ chave SSH criada")
        # se a chave já autentica, nada a fazer
        ja = subprocess.run(["ssh", "-o", "BatchMode=yes"] + SSH_BANCADA +
                            [f"{USUARIO}@{ip}", "true"],
                            capture_output=True, timeout=15)
        if ja.returncode == 0:
            print("  ✓ chave SSH já ativa no dongle")
        elif _instalar_chave(ip, senha, chave.with_suffix(".pub")):
            print("  ✓ chave SSH instalada (próximas conexões sem senha)")
        else:
            print("  · não consegui instalar a chave automaticamente.")
            print(f"    Rode manualmente 1x:  ssh-copy-id -o "
                  f"StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
                  f"{USUARIO}@{ip}")
    except Exception as e:
        print(f"  · chave SSH: {e}; seguirei com senha quando necessário.")


def _instalar_chave(ip, senha, pubfile):
    """
    Instala a chave pública no dongle usando ssh-copy-id (o método
    canônico). Se houver sshpass, passa a senha automaticamente; senão,
    o ssh-copy-id pede a senha uma única vez de forma interativa (o que
    é aceitável — é só 1 vez, e resolve TODAS as conexões seguintes).
    """
    opts = ["-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null"]
    if shutil.which("ssh-copy-id"):
        base = (["sshpass", "-p", senha] if shutil.which("sshpass") else [])
        try:
            # sem sshpass: interativo (herda o terminal, pede senha 1x).
            # com sshpass: silencioso.
            r = subprocess.run(
                base + ["ssh-copy-id"] + opts +
                ["-i", str(pubfile), f"{USUARIO}@{ip}"],
                capture_output=bool(base), timeout=40)
            if r.returncode == 0:
                return True
        except Exception:
            pass
    # fallback: append manual da chave via ssh (interativo, pede senha 1x)
    try:
        pub = Path(pubfile).read_text().strip()
        cmd = (f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
               f"grep -qF '{pub}' ~/.ssh/authorized_keys 2>/dev/null || "
               f"echo '{pub}' >> ~/.ssh/authorized_keys")
        r = subprocess.run(["ssh"] + opts + [f"{USUARIO}@{ip}", cmd],
                           timeout=40)
        return r.returncode == 0
    except Exception:
        return False


# ------------------------------------------------------------- helpers
def titulo(txt):
    print("\n" + "═" * 62)
    print("  " + txt)
    print("═" * 62)


def perguntar(txt, padrao_sim=True):
    sufixo = "[S/n]" if padrao_sim else "[s/N]"
    r = input(f"{txt} {sufixo} ").strip().lower()
    if not r:
        return padrao_sim
    return r in ("s", "sim", "y", "yes")


def rodar_modulo(caminho, args, descricao, interativo=True):
    """
    Executa um dos scripts-módulo como subprocesso, herdando o terminal
    (stdin/stdout) para que os prompts e barras de progresso deles
    apareçam normalmente. Retorna True se saiu com código 0.
    """
    if not caminho.exists():
        print(f"  ✗ módulo ausente: {caminho.name} — pulei '{descricao}'.")
        return False
    cmd = [PY, str(caminho)] + args
    print(f"\n→ {descricao}")
    print(f"  ({' '.join(cmd)})\n")
    try:
        # sem capture: o módulo fala direto com o usuário (prompts, senha)
        r = subprocess.run(cmd)
    except KeyboardInterrupt:
        print(f"\n  ⚠ '{descricao}' interrompido pelo usuário.")
        return False
    ok = (r.returncode == 0)
    print(f"\n  {'✓' if ok else '✗'} {descricao} "
          f"{'concluído' if ok else f'terminou com código {r.returncode}'}")
    return ok


def ssh_prefix(senha):
    if shutil.which("sshpass"):
        return ["sshpass", "-p", senha, "ssh"] + SSH_BANCADA
    return ["ssh"] + SSH_BANCADA


def dongle_responde(ip, senha):
    r = subprocess.run(ssh_prefix(senha) + [f"{USUARIO}@{ip}", "echo ok"],
                       capture_output=True)
    return b"ok" in (r.stdout or b"")


def remoto_sudo(ip, senha, comando):
    ssh = ssh_prefix(senha)
    full = f"sudo -S bash -c '{comando}'"
    r = subprocess.run(ssh + [f"{USUARIO}@{ip}", full],
                       input=(senha + "\n").encode(), capture_output=True)
    return r.returncode, r.stdout.decode(errors="replace"), \
        r.stderr.decode(errors="replace")


# ------------------------------------------------------------- serial USB
def configurar_serial_usb(ip, senha, ligar):
    """
    O acesso serial USB (/dev/ttyACM no PC) já vem habilitado na imagem
    OpenStick (ENABLE_ACM=1 no msm8916-usb-gadget.conf). O que decide se
    ele te dá um LOGIN é o getty amarrado ao ttyGS0 no lado do dongle.

    ligar=True  -> garante que existe login shell no serial (getty@ttyGS0)
    ligar=False -> desliga esse login (a porta fica muda; +seguro)

    Também ajusta ENABLE_ACM no .conf para persistir a escolha entre
    reinstalações do gadget, quando o arquivo existir.
    """
    if ligar:
        # habilita e sobe o getty no ttyGS0 (porta serial do gadget)
        cmd = ("systemctl enable --now getty@ttyGS0.service 2>/dev/null; "
               "true")
        titulo_op = "Ativando login no serial USB (getty@ttyGS0)"
    else:
        cmd = ("systemctl disable --now getty@ttyGS0.service 2>/dev/null; "
               "systemctl mask getty@ttyGS0.service 2>/dev/null; true")
        titulo_op = "Desligando login no serial USB (porta fica muda)"

    # persistência opcional no .conf do gadget (não falha se não existir)
    valor = "1" if ligar else "0"
    cmd += ("; f=/etc/msm8916-usb-gadget.conf; "
            "if [ -f \"$f\" ]; then "
            f"sed -i 's/^ENABLE_ACM=.*/ENABLE_ACM={valor}/' \"$f\"; fi")

    print(f"  → {titulo_op}")
    rc, out, err = remoto_sudo(ip, senha, cmd)
    if rc == 0:
        print("  ✓ serial USB " + ("ativado" if ligar else "desligado"))
        if ligar:
            print("     No PC:  ls /dev/ttyACM*  →  screen /dev/ttyACM0 115200")
    else:
        print(f"  ⚠ ajuste do serial retornou código {rc}")
        if err.strip():
            print("     " + err.strip().splitlines()[-1][:120])
    return rc == 0


# ------------------------------------------------------------- fluxo
def _backup_verificado_existe():
    """Há algum backup COM manifesto (verificado) em ./backup?"""
    bdir = BASE / "backup"
    if not bdir.is_dir():
        return False
    return any((p / "manifesto.json").exists()
               for p in bdir.glob("dongle_*"))


def _menu_falha_instalacao(args):
    """
    Menu ADAPTATIVO após falha de instalação: só oferece 'restaurar'
    quando existe backup verificado (senão seria mentira). Retorna:
      'pos'       -> seguir para otimização + painel
      'restaurar' -> rodar restaurar_backup.py
      'parar'     -> encerrar
    """
    tem_backup = _backup_verificado_existe()
    print("\n" + "─" * 58)
    print("  A instalação do Debian não concluiu.")
    print("─" * 58)
    if tem_backup:
        print("""
  O que deseja fazer?
   [1] Seguir para o pós (otimização + painel) mesmo assim
   [2] Restaurar o backup (voltar o dongle ao estado salvo)
   [3] Parar aqui
""")
        opcoes = {"1": "pos", "2": "restaurar", "3": "parar"}
        padrao = "3"
    else:
        print("""
  (Não há backup verificado para restaurar — este dongle não tinha
   um backup salvo, então 'restaurar' não se aplica.)

  O que deseja fazer?
   [1] Seguir para o pós (otimização + painel) mesmo assim
   [2] Parar aqui
""")
        opcoes = {"1": "pos", "2": "parar"}
        padrao = "2"
    resp = input(f"Escolha [{padrao}]: ").strip() or padrao
    return opcoes.get(resp, "parar")


def _firmware_faltando():
    """Lista os arquivos de firmware que faltam na pasta firmware/.
    Vazio = tudo presente. Usa a mesma lista do instalador."""
    fw = BASE / "firmware"
    esperados = ["gpt_both0.bin", "aboot.mbn", "hyp.mbn", "rpm.mbn",
                 "sbl1.mbn", "tz.mbn", "boot.bin", "rootfs.bin"]
    return [a for a in esperados if not (fw / a).exists()]


def main():
    ap = argparse.ArgumentParser(
        description="Orquestrador master do dongle OpenDongle")
    ap.add_argument("--ip", default=IP)
    ap.add_argument("--senha", default=SENHA)
    ap.add_argument("--so-pos", action="store_true",
                    help="Pula a pergunta e vai direto ao pós-instalação")
    ap.add_argument("--completo", action="store_true",
                    help="Pula a pergunta e roda o fluxo completo")
    ap.add_argument("--manter-4g", action="store_true",
                    help="Repassa ao otimizador (não desliga ModemManager)")
    args = ap.parse_args()

    titulo("OpenDongle — Preparação completa do dongle")
    print("""
Este assistente vai deixar o dongle redondo, em etapas:
  1) Debian (opcional)   2) Otimização   3) Portal   4) Serial USB
Cada etapa mostra seu próprio progresso. Você pode parar com Ctrl+C
entre etapas sem perder o que já foi feito.
""")

    # --- decisão inicial: completo ou só pós? ---
    if args.completo:
        fazer_install = True
    elif args.so_pos:
        fazer_install = False
    else:
        print("Este dongle JÁ tem o Debian instalado (OpenStick)?")
        print("  • Sim  → pulo a instalação e faço só o pós (otim.+portal)")
        print("  • Não  → faço o fluxo completo (instalo o Debian primeiro)")
        fazer_install = not perguntar(
            "O Debian já está instalado neste dongle?", padrao_sim=True)

    # ===== ETAPA 1: instalação (opcional) =====
    if fazer_install:
        titulo("ETAPA 1/4 — Instalação do Debian")

        # Verifica se o firmware está presente ANTES de repassar ao
        # instalador (evita o erro "Firmware ausente" no meio do fluxo).
        faltando = _firmware_faltando()
        if faltando:
            print("⚠ O firmware do OpenStick não está baixado nesta pasta.")
            print(f"  Faltam: {', '.join(faltando[:3])}"
                  f"{'...' if len(faltando) > 3 else ''}")
            print("""
  Você pode:
   • Baixar agora (roda setup_estrutura.py, ~143MB) e seguir; ou
   • Pular a instalação — útil se você vai RESTAURAR um dongle
     brickado ou investigar a placa manualmente por fora.
""")
            if perguntar("Baixar o firmware agora e continuar a instalação?",
                         padrao_sim=True):
                if not rodar_modulo(BASE / "setup_estrutura.py", [],
                                    "Download do firmware (setup_estrutura)"):
                    print("Download não concluiu. Pulei a instalação.")
                    fazer_install = False
            else:
                print("Ok, pulei a instalação. (Para restaurar um brick: "
                      "python3 restaurar_backup.py)")
                fazer_install = False

    if fazer_install:
        print("Repasso o controle ao instalador (backup, flash, verificação).")
        continuar = perguntar(
            "Este dongle está em EDL e pronto para o fluxo completo?",
            padrao_sim=True)
        if not continuar:
            print("Ok, pulei a instalação a seu pedido.")
            fazer_install = False
        else:
            ok = rodar_modulo(MOD_INSTALL, [], "Instalação do Debian")
            if not ok:
                escolha = _menu_falha_instalacao(args)
                if escolha == "parar":
                    print("Encerrando. Rode --so-pos quando o Debian "
                          "estiver no ar, ou reinicie o fluxo.")
                    return
                if escolha == "restaurar":
                    rodar_modulo(BASE.parent / "ferramentas" / "restaurar_backup.py", [],
                                 "Restauração do backup")
                    print("Restauração acionada. Encerrando o fluxo — "
                          "verifique o dongle e rode de novo se desejar.")
                    return
                # escolha == "pos": segue para otimização + painel
                print("Ok, seguindo para o pós a seu pedido.")

    if not fazer_install:
        titulo("ETAPA 1/4 — Instalação do Debian (PULADA)")
        print("Seguindo direto ao pós (otimização + painel).")

    # --- daqui pra frente, precisamos falar com o dongle via SSH ---
    print("\nVerificando acesso ao dongle via rede USB...")
    for tentativa in range(24):   # ~2 min
        if dongle_responde(args.ip, args.senha):
            print(f"  ✓ dongle responde em {args.ip}")
            break
        print(f"  … aguardando {args.ip} ({tentativa+1}/24)", end="\r")
        time.sleep(5)
    else:
        print(f"\n  ✗ não conectei em {args.ip}. Confira a rede 'linux' "
              "conectada. Abortando o pós.")
        return

    # auto-suficiência: never-default + chave SSH (elimina pré-requisitos)
    preparar_pc(args.ip, args.senha)

    # ===== ETAPA 2: otimização =====
    titulo("ETAPA 2/4 — Otimização (durabilidade + velocidade)")
    otim_args = ["--ip", args.ip, "--senha", args.senha]
    if args.manter_4g:
        otim_args.append("--manter-4g")
    rodar_modulo(MOD_OTIM, otim_args, "Otimização do sistema")

    # ===== ETAPA 3: painel OpenDongle =====
    titulo("ETAPA 3/4 — Painel OpenDongle (config + opendongle.local)")
    if perguntar("Instalar o painel OpenDongle neste dongle?", padrao_sim=True):
        rodar_modulo(MOD_PORTAL,
                     ["--ip", args.ip, "--senha", args.senha],
                     "Instalação do painel OpenDongle")
    else:
        print("  Painel pulado a seu pedido.")

    # ===== ETAPA 4: acesso serial USB (pergunta por dongle) =====
    titulo("ETAPA 4/4 — Acesso serial via USB")
    print("""
O acesso por cabo USB como terminal serial (/dev/ttyACM no seu PC) já
vem habilitado na imagem. Ele é prático (terminal direto sem rede), mas
é também uma porta de entrada SEM senha de rede — para um produto que
guarda dados, o mais seguro é deixá-lo DESLIGADO.
""")
    quer_serial = perguntar(
        "Manter o acesso serial USB LIGADO neste dongle?", padrao_sim=False)
    configurar_serial_usb(args.ip, args.senha, ligar=quer_serial)

    # ===== resumo =====
    titulo("CONCLUÍDO")
    print(f"""
Dongle preparado em {args.ip}:
  • Debian ............ {'instalado agora' if fazer_install else 'já existia'}
  • Otimização ........ aplicada (rode um reboot para assentar)
  • Painel OpenDongle . conforme sua escolha acima
  • Serial USB ........ {'LIGADO' if quer_serial else 'desligado (+seguro)'}

Acesso de administração:
  ssh {USUARIO}@{args.ip}                         (senha atual: {args.senha})
  sftp://{USUARIO}@{args.ip}  no Arquivos (GNOME)  para ler dados
{'  screen /dev/ttyACM0 115200                     terminal por cabo USB' if quer_serial else ''}

Sugestão de próximo passo: reiniciar o dongle para a otimização assentar.
""")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompido. As etapas já concluídas foram preservadas.")
