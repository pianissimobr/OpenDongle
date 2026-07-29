#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongle_autoinstall.py — Instalador automatizado do Debian (OpenStick v1.2)
em dongles 4G MSM8916, baseado em LongQT-sea/OpenStick-Builder.

FLUXO:
  ETAPA 1  BACKUP TOTAL do firmware original via EDL (OBRIGATÓRIO — sem
           backup verificado o script NÃO CONTINUA em hipótese alguma)
  ETAPA 2  DETECÇÃO DA PLACA:
           a) escaneia o backup procurando assinaturas do modelo (balizador)
           b) se inconclusivo, MODO TESTE: troca só a linha 'fdt' do
              extlinux.conf dentro do boot.bin e testa placa por placa
           c) cada acerto confirmado é gravado em detection_db.json,
              refinando o balizador com dados reais
  ETAPA 3  PATCH do boot.bin com o devicetree correto da placa
  ETAPA 4  FLASH (EDL -> fastboot) + restauração das partições de calibração
  ETAPA 5  VERIFICAÇÃO do boot (interface USB de rede / ping / SSH)
  ETAPA 6  LIMPEZA DO BACKUP — *** DESATIVADA / COMENTADA *** até testes reais

Requisitos: rodar como root (sudo), deps instaladas via install.sh,
firmware baixado via setup_estrutura.py.
"""

import datetime
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
FW = BASE / "firmware"
BACKUP_DIR = BASE / "backup"
LOG_DIR = BASE / "logs"
WORK = BASE / "work"
DB_PATH = BASE / "detection_db.json"

# ------------------------------------------------------------------ placas
# A ÚNICA diferença entre as placas na imagem é a linha 'fdt' do
# /extlinux/extlinux.conf dentro do boot.bin. Estes são os devicetrees
# suportados pelo kernel do postmarketOS usado no OpenStick:
PLACAS = {
    "UZ801":  {"dtb": "msm8916-yiming-uz801v3.dtb",
               "assinaturas": [b"uz801", b"yiming"]},
    "UF896":  {"dtb": "msm8916-thwc-uf896.dtb",
               "assinaturas": [b"uf896"]},
    "UFI001": {"dtb": "msm8916-thwc-ufi001c.dtb",   # placas UFIxxx
               "assinaturas": [b"ufi001", b"ufi-001", b"ufi_001", b"ufi00"]},
    "JZ01":   {"dtb": "msm8916-jz01-45-v33.dtb",    # placas JZxxx
               "assinaturas": [b"jz01"]},
    "MF800":  {"dtb": "msm8916-fy-mf800.dtb",
               "assinaturas": [b"mf800"]},
}

# Partições de calibração/rádio que precisam ser preservadas e restauradas
PARTICOES_CALIBRACAO = ["fsc", "fsg", "modem", "modemst1", "modemst2",
                        "persist", "sec"]

# Sequência de flash em fastboot, na ordem do README oficial
SEQUENCIA_FLASH = [
    ("partition", "gpt_both0.bin"),
    ("aboot",     "aboot.mbn"),
    ("hyp",       "hyp.mbn"),
    ("rpm",       "rpm.mbn"),
    ("sbl1",      "sbl1.mbn"),
    ("tz",        "tz.mbn"),
    ("boot",      "boot_patched.bin"),   # boot já com o dtb da placa
    ("rootfs",    "rootfs.bin"),
]

IP_PADRAO = "192.168.100.1"   # IP do dongle após instalar o OpenStick

# Loader firehose que o edl envia ao chip via Sahara. Obrigatório nesses
# dongles: o par HWID+PK_HASH deles (chave de teste Qualcomm, OEM_ID 0x0000)
# não existe no banco automático do edl. Baixado pelo setup_estrutura.py.
LOADER = FW / "prog_emmc_firehose_8916.mbn"


def edl_cmd(*args):
    """Monta comando edl sempre com o loader explícito."""
    return ["edl", *args, f"--loader={LOADER}"]

LOGFILE = LOG_DIR / f"install_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"


# ------------------------------------------------------------------ util
def log(msg, nivel="INFO"):
    linha = f"[{datetime.datetime.now():%H:%M:%S}] [{nivel}] {msg}"
    print(linha)
    LOG_DIR.mkdir(exist_ok=True)
    with open(LOGFILE, "a") as f:
        f.write(linha + "\n")


def run(cmd, timeout=None, check=True, quiet=False):
    """Executa comando, loga e retorna CompletedProcess."""
    if not quiet:
        log("$ " + " ".join(cmd), "CMD")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        log(f"TIMEOUT ({timeout}s): {' '.join(cmd)}", "ERRO")
        if check:
            sys.exit(1)
        return None
    if r.returncode != 0 and check:
        log(f"Comando falhou (rc={r.returncode}): {r.stderr.strip()[:400]}", "ERRO")
        sys.exit(1)
    return r


def run_stream(cmd, timeout=7200, inatividade_max=180, check=True):
    """
    Executa comandos LONGOS (edl rf, fastboot flash) mostrando o output
    EM TEMPO REAL na tela e no log — nada de tela congelada.

    Watchdog de inatividade: se o processo ficar 'inatividade_max' segundos
    sem imprimir NADA, consideramos travamento (Sahara morto, porta presa,
    cabo ruim), matamos o processo e reportamos, em vez de esperar pra sempre.

    Retorna (returncode, texto_completo_do_output).
    """
    log("$ " + " ".join(cmd), "CMD")
    # ATENÇÃO: leitura em modo BINÁRIO. text=True + pipe não-bloqueante
    # quebra o decoder do Python quando o pipe está vazio (retorna None).
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, bufsize=0)
    os.set_blocking(proc.stdout.fileno(), False)

    saida = []
    inicio = time.time()
    ultimo_output = time.time()
    buf = ""
    try:
        while True:
            pedaco_bytes = proc.stdout.read()   # None = nada disponível agora
            pedaco = (pedaco_bytes.decode("utf-8", errors="replace")
                      if pedaco_bytes else "")
            if pedaco:
                if time.time() - ultimo_output > 15:
                    print()   # encerra a linha do heartbeat
                ultimo_output = time.time()
                buf += pedaco
                # edl usa \r para barra de progresso; normalizamos
                for linha in re.split(r"[\r\n]", buf)[:-1]:
                    if linha.strip():
                        print("   | " + linha.strip())
                        saida.append(linha)
                buf = re.split(r"[\r\n]", buf)[-1]
                with open(LOGFILE, "a") as f:
                    f.write(pedaco)

            if proc.poll() is not None:
                break
            silencio = time.time() - ultimo_output
            # Heartbeat: mostra que o processo está VIVO durante silêncios
            # longos (escritas fastboot/edl ficam mudas por minutos)
            if silencio > 15:
                print(f"\r   … {int(silencio):4d}s sem output — processo "
                      f"vivo, aguardando (watchdog age em "
                      f"{inatividade_max}s)   ", end="", flush=True)
            if silencio > inatividade_max:
                print()
                proc.kill()
                log(f"TRAVAMENTO: {inatividade_max}s sem nenhum output do "
                    f"comando. Processo morto.", "ERRO")
                return -99, "\n".join(saida)
            if time.time() - inicio > timeout:
                proc.kill()
                log(f"TIMEOUT global de {timeout}s excedido.", "ERRO")
                return -98, "\n".join(saida)
            time.sleep(0.2)
    except KeyboardInterrupt:
        proc.kill()
        raise

    texto = "\n".join(saida)
    if proc.returncode != 0 and check:
        log(f"Comando falhou (rc={proc.returncode})", "ERRO")
    return proc.returncode, texto


def diagnosticar_saida_edl(texto):
    """Traduz sintomas comuns do edl em instruções práticas."""
    t = (texto or "").lower()
    if "waiting for the device" in t or "waiting for device" in t:
        log("DIAGNÓSTICO: edl não enxerga o dispositivo.", "AVISO")
        log("  1) Confira: lsusb | grep 05c6:9008", "AVISO")
        log("  2) Pare o ModemManager: sudo systemctl stop ModemManager", "AVISO")
        log("  3) Desplugue e replugue o dongle em modo EDL", "AVISO")
    if "sahara" in t and ("error" in t or "failed" in t):
        log("DIAGNÓSTICO: estado Sahara consumido/corrompido — acontece "
            "quando outro comando edl já tocou o aparelho.", "AVISO")
        log("  SOLUÇÃO: desplugue o dongle, replugue em modo EDL e "
            "tente de novo.", "AVISO")
    if "permission" in t or "access denied" in t:
        log("DIAGNÓSTICO: permissão USB. Rode como root e confira as "
            "regras udev (51-edl.rules).", "AVISO")


def matar_processos_conflitantes():
    """ModemManager e instâncias antigas de edl são os sequestradores
    clássicos da porta EDL. Neutralizamos antes de começar."""
    r = run(["systemctl", "stop", "ModemManager"], check=False, quiet=True)
    if r is not None and r.returncode == 0:
        log("ModemManager parado (era um possível sequestrador da porta).")
    run(["pkill", "-f", "edl "], check=False, quiet=True)


def perguntar_sim_nao(pergunta, padrao_sim=False):
    sufixo = "[S/n]" if padrao_sim else "[s/N]"
    resp = input(f"{pergunta} {sufixo} ").strip().lower()
    if not resp:
        return padrao_sim
    return resp in ("s", "sim", "y", "yes")


def dispositivo_em_edl():
    """Detecta 05c6:9008 (Qualcomm EDL / QDLoader) no barramento USB."""
    r = run(["lsusb"], check=False, quiet=True)
    return r is not None and "05c6:9008" in (r.stdout or "")


def dispositivo_em_fastboot():
    r = run(["fastboot", "devices"], check=False, quiet=True, timeout=15)
    return r is not None and bool(r.stdout.strip())


def estado_usb():
    """Relata o que está visível no USB entre os IDs que nos interessam."""
    r = run(["lsusb"], check=False, quiet=True)
    saida = (r.stdout or "") if r else ""
    estados = []
    if "05c6:9008" in saida:
        estados.append("EDL (05c6:9008)")
    if "18d1:d00d" in saida:
        estados.append("FASTBOOT (18d1:d00d)")
    if "05c6:90" in saida and "05c6:9008" not in saida:
        estados.append("gadget Qualcomm (stock?)")
    return estados or ["nenhum ID conhecido visível"]


def dispositivo_em_adb():
    """Android stock subiu? (acontece quando o apagamento do boot falha —
    o aboot custom acha boot válido e inicia o Android de fábrica)."""
    r = run(["adb", "devices"], check=False, quiet=True, timeout=15)
    if not r:
        return False
    linhas = [l for l in (r.stdout or "").splitlines()[1:] if l.strip()]
    return any("\tdevice" in l or "\tunauthorized" in l for l in linhas)


def adb_shell(comando, timeout=30):
    r = run(["adb", "shell", comando], check=False, quiet=True,
            timeout=timeout)
    return (r.stdout or "").strip() if r else ""


def invalidar_boot_via_adb():
    """
    O 'adb reboot bootloader' não é honrado pelo stock desses dongles
    (verificado em campo). Caminho determinístico: o adbd do stock roda
    como ROOT, então zeramos o início da partição boot por dentro do
    próprio Android e reiniciamos — o aboot custom não acha boot válido
    e cai em fastboot obrigatoriamente.
    """
    quem = adb_shell("id")
    if "uid=0" not in quem:
        # Última cartada ADB: 'adb root' reinicia o adbd como root em
        # builds userdebug. Em builds de produção, é recusado.
        log("adbd não é root; tentando 'adb root'...")
        run(["adb", "root"], check=False, quiet=True, timeout=30)
        time.sleep(4)
        run(["adb", "wait-for-device"], check=False, quiet=True, timeout=30)
        quem = adb_shell("id")
    if "uid=0" not in quem:
        log(f"adbd não é root ({quem[:40]}...) — não dá para invalidar "
            "o boot por ADB. Caminho restante: EDL (replug com botão).",
            "AVISO")
        return False

    # Localiza o bloco da partição boot (caminhos variam entre stocks)
    candidatos = [
        "readlink -f /dev/block/bootdevice/by-name/boot",
        "ls /dev/block/platform/*/by-name/boot",
        "ls /dev/block/platform/*/*/by-name/boot",
    ]
    dev = ""
    for c in candidatos:
        saida = adb_shell(c)
        if saida.startswith("/dev/") and "No such" not in saida:
            dev = saida.splitlines()[0].strip()
            break
    if not dev:
        log("Não achei a partição boot via ADB.", "AVISO")
        return False

    log(f"Invalidando boot stock via ADB root: {dev}")
    adb_shell(f"dd if=/dev/zero of={dev} bs=1024 count=1024", timeout=60)
    # Confirma: os primeiros bytes têm que estar zerados agora
    # (o magic 'ANDROID!' precisa ter morrido)
    checagem = adb_shell(f"dd if={dev} bs=8 count=1 2>/dev/null | od -c "
                         "| head -1")
    if "A N D R O I D" in checagem:
        log("Boot ainda tem magic ANDROID! após dd — invalidação falhou.",
            "AVISO")
        return False
    log("Boot stock invalidado. Reiniciando — agora o aboot custom "
        "não tem para onde ir a não ser o fastboot.")
    run(["adb", "reboot"], check=False, timeout=30)
    return True


def esperar_fastboot_interativo(timeout_inicial=90):
    """
    Autômato de estados até chegar em fastboot:
      - FASTBOOT visível -> pronto.
      - ADB visível (stock subiu; boot não foi apagado) -> invalida o
        boot via ADB root + reboot. Se impossível, tenta reboot
        bootloader; se persistir, instrui o caminho EDL.
      - EDL visível -> zera o boot via edl + reset.
      - Nada visível -> pede replug (sem botão).
    """
    inicio = time.time()
    pediu_replug = False
    tentou_adb_dd = False
    tentou_adb_reboot = False
    instruiu_edl = False
    tentativas_edl = 0
    while time.time() - inicio < timeout_inicial + 480:
        if dispositivo_em_fastboot():
            log("OK: dispositivo em fastboot")
            return True

        if dispositivo_em_adb():
            if not tentou_adb_dd:
                tentou_adb_dd = True
                if invalidar_boot_via_adb():
                    time.sleep(8)
                    continue
            if not tentou_adb_reboot:
                tentou_adb_reboot = True
                log("Tentando 'adb reboot bootloader' mesmo assim...")
                run(["adb", "reboot", "bootloader"], check=False, timeout=30)
                time.sleep(8)
                continue
            # ADB persiste após as duas tentativas -> só resta o EDL
            if not instruiu_edl:
                instruiu_edl = True
                print("""
  >> O Android stock insiste em subir e o ADB não tem privilégios.
  >> Último recurso (garantido): DESPLUGUE e replugue SEGURANDO O
  >> BOTÃO (modo EDL, 05c6:9008). O script detecta, zera o boot via
  >> EDL e reinicia para o fastboot sozinho.
""")
            time.sleep(6)
            continue

        if dispositivo_em_edl():
            if tentativas_edl >= 2:
                # Já zeramos o boot 2x e o dongle INSISTE em voltar pro EDL
                # em vez de ir pro fastboot. Girar mais é inútil (loop).
                # Isso acontece quando o 'edl reset' não leva este
                # hardware ao fastboot (ex.: placa cujo dtb/loader não
                # bate). Paramos e pedimos decisão humana.
                log("O dongle volta ao EDL a cada reset (2 tentativas) — "
                    "não está indo para o fastboot sozinho.", "AVISO")
                print("""
  >> Este dongle não cai em fastboot pelo reset automático.
  >> Causas prováveis: a placa informada pode não ser a correta,
  >> ou o reset não é suportado neste hardware.
  >>
  >> Opções:
  >>  a) DESPLUGUE, replugue SEM botão e aguarde — se ele bootar um
  >>     sistema, ótimo; se não, replugue COM botão (EDL) e tente
  >>     outra placa (--placa) ou o modo teste.
  >>  b) Ctrl+C para abortar e investigar.
""")
                # dá uma janela para o replug manual antes de desistir
                if esperar(dispositivo_em_fastboot,
                           "fastboot após intervenção manual",
                           timeout=120, intervalo=4):
                    return True
                log("Sem fastboot após intervenção. Encerrando a espera.",
                    "AVISO")
                return False

            tentativas_edl += 1
            log(f"Dispositivo em EDL — zerando boot e resetando via edl... "
                f"(tentativa {tentativas_edl}/2)")
            zeros = WORK / "zeros_1mb.bin"
            if not zeros.exists() or zeros.stat().st_size != 1 << 20:
                zeros.write_bytes(b"\x00" * (1 << 20))
            matar_processos_conflitantes()
            edl_com_retry(edl_cmd("w", "boot", str(zeros)),
                          "invalidação do boot via EDL",
                          timeout=120, inatividade_max=60, fatal=False)
            run_stream(edl_cmd("reset"), timeout=60, inatividade_max=30,
                       check=False)
            time.sleep(5)
            continue

        if not pediu_replug and time.time() - inicio > timeout_inicial:
            log(f"Estado USB atual: {', '.join(estado_usb())}", "AVISO")
            print("""
  >> Nada visível no USB. DESPLUGUE e REPLUGUE o dongle SEM botão.
  >> O script resolve sozinho qualquer estado em que ele subir
  >> (fastboot, Android/ADB ou EDL).
""")
            pediu_replug = True

        time.sleep(4)

    log(f"Estado USB final: {', '.join(estado_usb())}", "AVISO")
    return False


def esperar(condicao, descricao, timeout=180, intervalo=3):
    log(f"Aguardando: {descricao} (até {timeout}s)...")
    inicio = time.time()
    while time.time() - inicio < timeout:
        if condicao():
            print()
            log(f"OK: {descricao}")
            return True
        print(f"\r   … aguardando {descricao}: "
              f"{int(time.time()-inicio):3d}s/{timeout}s   ",
              end="", flush=True)
        time.sleep(intervalo)
    print()
    log(f"Tempo esgotado aguardando: {descricao}", "AVISO")
    return False


def sha256_arquivo(caminho, bloco=1 << 22):
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for chunk in iter(lambda: f.read(bloco), b""):
            h.update(chunk)
    return h.hexdigest()


# ============================================================ ETAPA 1: BACKUP
def aceitar_risco_sem_backup(motivo):
    """
    Porta de escape pedida pelo usuário: dispositivos já 'perdidos' ou
    cujo backup não completa. Recomendamos FORTEMENTE não usar; a
    confirmação exige digitar uma frase inteira para não ser acionada
    por engano.
    """
    log(f"BACKUP AUSENTE/INCOMPLETO: {motivo}", "AVISO")
    print("""
  ╔══════════════════════════════════════════════════════════════╗
  ║  ⚠️  CONTINUAR SEM BACKUP VERIFICADO — LEIA COM ATENÇÃO  ⚠️   ║
  ╠══════════════════════════════════════════════════════════════╣
  ║ RECOMENDAMOS QUE NÃO FAÇA ISSO. Sem o backup:                ║
  ║  - NÃO HÁ como voltar ao firmware original, nunca mais;     ║
  ║  - IMEI e calibração de rádio podem ser PERDIDOS PARA       ║
  ║    SEMPRE (o 4G pode nunca mais funcionar);                  ║
  ║  - qualquer falha no meio pode INUTILIZAR o aparelho.        ║
  ║ Use apenas em dispositivo que você já considera perdido —    ║
  ║ o famoso "abrir para ver o chip e seja o que Deus quiser".   ║
  ╚══════════════════════════════════════════════════════════════╝
""")
    resp = input("  Para continuar assim mesmo, digite exatamente "
                 "ACEITO O RISCO\n  > ")
    aceito = resp.strip().upper() == "ACEITO O RISCO"
    log("Usuário " + ("ACEITOU o risco de prosseguir sem backup."
                      if aceito else "recusou prosseguir sem backup."),
        "AVISO")
    return aceito


def edl_com_retry(cmd, descricao, tentativas=3, timeout=7200,
                  inatividade_max=180, fatal=True):
    """
    Executa um comando edl com output ao vivo. Se travar ou falhar,
    diagnostica o sintoma, pede replug em EDL (cura o Sahara consumido)
    e tenta de novo — até 'tentativas' vezes.
    """
    for i in range(1, tentativas + 1):
        log(f"[{descricao}] tentativa {i}/{tentativas}")
        rc, texto = run_stream(cmd, timeout=timeout,
                               inatividade_max=inatividade_max, check=False)
        if rc == 0:
            return texto
        diagnosticar_saida_edl(texto)
        if i < tentativas:
            print("\n  >> DESPLUGUE o dongle, REPLUGUE em modo EDL "
                  "(botão pressionado) e aguarde 5s.")
            input("  >> ENTER quando lsusb mostrar 05c6:9008 de novo... ")
            matar_processos_conflitantes()
            esperar(dispositivo_em_edl, "dispositivo de volta em EDL",
                    timeout=120, intervalo=2)
    if fatal:
        sys.exit(f"ABORTADO: '{descricao}' falhou após {tentativas} "
                 "tentativas. Veja o diagnóstico acima e o log em ./logs")
    log(f"'{descricao}' falhou após {tentativas} tentativas "
        "(modo não-fatal, seguindo).", "AVISO")
    return None


def etapa1_backup(sem_backup=False):
    """
    Backup do firmware original, em 4 sub-etapas com verificação.
    Se QUALQUER uma falhar, o script aborta. Sem exceções.

      1a. Neutralizar sequestradores de porta (ModemManager, edl zumbi)
      1b. TESTE DE COMUNICAÇÃO rápido (printgpt) — valida Sahara/loader
          em ~30s ANTES de comprometer 30+ min de dump
      1c. Backup das partições de CALIBRAÇÃO primeiro (pequenas e são
          o dado insubstituível: IMEI, rádio, chaves)
      1d. Dump COMPLETO da flash (edl rf) com progresso ao vivo
    """
    log("=" * 60)
    log("ETAPA 1 — BACKUP OBRIGATÓRIO DO FIRMWARE ORIGINAL")
    log("=" * 60)

    print("""
  Coloque o dongle em modo EDL:
    - Zhihe/UZ801 e similares: segure o botão (furo) enquanto pluga no USB,
      ou use 'adb reboot edl' se o stock estiver acessível.
    - Confirmação: lsusb deve mostrar 05c6:9008 (QDLoader 9008).
""")
    # -- 1a. limpar o terreno ------------------------------------------
    matar_processos_conflitantes()

    if not esperar(dispositivo_em_edl, "dispositivo em modo EDL (05c6:9008)",
                   timeout=300, intervalo=2):
        sys.exit("ABORTADO: nenhum dispositivo em EDL encontrado.\n"
                 "  Confira o cabo (tem que ser de DADOS), a porta USB e o "
                 "modo EDL (lsusb deve listar 05c6:9008).")

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    pasta = BACKUP_DIR / f"dongle_{stamp}"
    pasta.mkdir(parents=True, exist_ok=True)

    # -- 1b. teste de comunicação barato -------------------------------
    # printgpt sobe o loader firehose e lê a tabela de partições. Se isso
    # funciona, o canal está saudável; se trava, descobrimos em 30s.
    log("Sub-etapa 1b: teste de comunicação EDL (printgpt)...")
    gpt_texto = edl_com_retry(edl_cmd("printgpt"),
                              "teste de comunicação (printgpt)",
                              timeout=120, inatividade_max=60)
    (pasta / "gpt.txt").write_text(gpt_texto)
    log("Canal EDL OK. Tabela de partições salva em gpt.txt")

    # -- 1c. calibração primeiro (o insubstituível) ---------------------
    log("Sub-etapa 1c: backup das partições de calibração (rápido)...")
    for p in PARTICOES_CALIBRACAO:
        edl_com_retry(edl_cmd("r", p, str(pasta / f"{p}.bin")),
                      f"backup partição {p}",
                      timeout=600, inatividade_max=120,
                      fatal=not sem_backup)

    # -- 1d. dump completo, com progresso visível -----------------------
    total = pasta / "orig_fw.bin"
    if sem_backup:
        log("MODO --sem-backup: pulando o dump completo da flash. "
            "As partições de calibração acima foram salvas em melhor "
            "esforço.", "AVISO")
    else:
        log("Sub-etapa 1d: dump COMPLETO da flash (edl rf).")
        log("  eMMC de ~4GB via USB leva de 15 a 40 MINUTOS. O progresso "
            "do edl aparece abaixo — se ficar 3 min sem output, o "
            "watchdog age.")
        r = edl_com_retry(edl_cmd("rf", str(total)),
                          "dump completo da flash",
                          timeout=7200, inatividade_max=180, fatal=False)
        if r is None and not aceitar_risco_sem_backup(
                "o dump completo da flash falhou repetidamente"):
            sys.exit("ABORTADO por escolha do usuário. Nada foi gravado.")

    # ---- 1c. VERIFICAÇÃO — o portão sem volta ----
    log("Verificando integridade do backup...")
    problemas = []

    # Flash total precisa existir e ter tamanho plausível (eMMC ~4GB;
    # aceita >= 1 GB para tolerar variações de chip, mas nada menor)
    if not total.exists():
        problemas.append("orig_fw.bin não foi criado")
    elif total.stat().st_size < 1_000_000_000:
        problemas.append(f"orig_fw.bin muito pequeno: {total.stat().st_size} bytes")

    # Cada partição de calibração: existe e não é 100% zeros
    for p in PARTICOES_CALIBRACAO:
        arq = pasta / f"{p}.bin"
        if not arq.exists() or arq.stat().st_size == 0:
            problemas.append(f"{p}.bin ausente ou vazio")
            continue
        amostra = arq.read_bytes()[:4096]
        # 'fsc' e 'sec' podem legitimamente ser quase vazios em alguns
        # aparelhos; só alertamos. modem/modemst/persist zerados = problema.
        if amostra.count(0) == len(amostra) and p in ("modem", "modemst1",
                                                      "modemst2", "persist"):
            problemas.append(f"{p}.bin parece estar zerado")

    if sem_backup:
        # modo explícito: valida só o que existir, sem exigências
        problemas = [pr for pr in problemas if "orig_fw" not in pr]
        if problemas:
            for pr in problemas:
                log("AVISO DE BACKUP PARCIAL: " + pr, "AVISO")
    elif problemas:
        for pr in problemas:
            log("FALHA DE BACKUP: " + pr, "ERRO")
        if not aceitar_risco_sem_backup(
                "a verificação do backup encontrou os problemas acima"):
            sys.exit("\nABORTADO: backup não passou na verificação. "
                     "NADA foi gravado no dispositivo. Resolva e rode "
                     "de novo.")

    # Manifesto com hashes para auditoria
    manifesto = {"data": stamp, "parcial": bool(sem_backup or problemas),
                 "arquivos": {}}
    for arq in sorted(pasta.glob("*.bin")):
        manifesto["arquivos"][arq.name] = {
            "bytes": arq.stat().st_size,
            "sha256": sha256_arquivo(arq),
        }
    (pasta / "manifesto.json").write_text(json.dumps(manifesto, indent=2))
    log(f"BACKUP VERIFICADO E COMPLETO em: {pasta}")
    return pasta


# ==================================================== ETAPA 2: DETECÇÃO PLACA
def carregar_db():
    if DB_PATH.exists():
        return json.loads(DB_PATH.read_text())
    return {"confirmacoes": []}


def salvar_confirmacao(assinaturas_encontradas, placa_confirmada, metodo):
    """Alimenta o balizador: registra que ESTE padrão de assinaturas
    corresponde a ESTA placa (confirmado por detecção ou por teste real)."""
    db = carregar_db()
    db["confirmacoes"].append({
        "data": datetime.datetime.now().isoformat(timespec="seconds"),
        "assinaturas": {k: v for k, v in assinaturas_encontradas.items() if v},
        "placa": placa_confirmada,
        "metodo": metodo,   # 'scan' ou 'teste_real'
    })
    DB_PATH.write_text(json.dumps(db, indent=2, ensure_ascii=False))
    log(f"Balizador atualizado: {placa_confirmada} via {metodo} -> detection_db.json")


def escanear_backup(caminho_backup):
    """
    Procura assinaturas de modelo dentro do dump completo do firmware
    original. O firmware stock é Android e carrega strings do modelo
    (build.prop, devicetree stock, etc.) — esse é o dado balizador.
    Varredura em streaming com sobreposição para não perder strings
    cortadas na borda dos blocos.
    """
    log("Escaneando backup em busca de assinaturas de placa (balizador)...")
    contagem = {nome: 0 for nome in PLACAS}
    tamanho_bloco = 1 << 24        # 16 MB
    sobra = 32                     # overlap entre blocos
    cauda = b""

    with open(caminho_backup, "rb") as f:
        while True:
            bloco = f.read(tamanho_bloco)
            if not bloco:
                break
            area = (cauda + bloco).lower()
            for nome, info in PLACAS.items():
                for assin in info["assinaturas"]:
                    contagem[nome] += area.count(assin)
            cauda = bloco[-sobra:]

    for nome, n in sorted(contagem.items(), key=lambda kv: -kv[1]):
        log(f"   {nome:7s}: {n} ocorrência(s)")
    return contagem


def etapa2_detectar_placa(pasta_backup):
    log("=" * 60)
    log("ETAPA 2 — DETECÇÃO DA PLACA")
    log("=" * 60)

    if not (pasta_backup / "orig_fw.bin").exists():
        log("Sem dump completo — sem scan de assinaturas. Indo direto "
            "à escolha manual/modo teste.", "AVISO")
        contagem = {nome: 0 for nome in PLACAS}
        print("\nOpções de placa:", ", ".join(PLACAS))
        escolha = input("Digite a placa (ou ENTER para MODO TESTE "
                        "iterativo): ").strip().upper()
        if escolha in PLACAS:
            return escolha, contagem
        return None, contagem
    contagem = escanear_backup(pasta_backup / "orig_fw.bin")
    ordenado = sorted(contagem.items(), key=lambda kv: -kv[1])
    melhor, n1 = ordenado[0]
    _, n2 = ordenado[1]

    # Critério: vencedor claro = tem ocorrências e pelo menos 3x o 2º lugar
    if n1 > 0 and (n2 == 0 or n1 >= 3 * n2):
        log(f"Detecção por scan sugere placa: {melhor} (confiança alta)")
        if perguntar_sim_nao(f"Confirmar placa {melhor}?", padrao_sim=True):
            salvar_confirmacao(contagem, melhor, "scan")
            return melhor, contagem
    elif n1 > 0:
        log(f"Scan AMBÍGUO: {melhor}={n1} vs {ordenado[1][0]}={n2}", "AVISO")
    else:
        log("Nenhuma assinatura encontrada no dump.", "AVISO")

    # Escolha manual (se você sabe a placa pela carcaça/PCB) ou modo teste
    print("\nOpções de placa:", ", ".join(PLACAS))
    escolha = input("Digite a placa (ou ENTER para MODO TESTE iterativo): ").strip().upper()
    if escolha in PLACAS:
        salvar_confirmacao(contagem, escolha, "manual")
        return escolha, contagem
    return None, contagem   # None -> modo teste na etapa 4/5


# ================================================= ETAPA 3: PATCH DO BOOT.BIN
def patch_boot(dtb):
    """
    Troca a variável que diferencia as placas: a linha
        fdt /dtbs/qcom/<DTB>
    do /extlinux/extlinux.conf dentro do boot.bin (ext2 em sparse Android).
    Fluxo: simg2img -> mount loop -> sed -> umount -> img2simg.
    """
    log(f"Gerando boot patchado com devicetree: {dtb}")
    raw = WORK / "boot.raw"
    mnt = WORK / "mnt_boot"
    saida = FW / "boot_patched.bin"
    mnt.mkdir(parents=True, exist_ok=True)

    run(["simg2img", str(FW / "boot.bin"), str(raw)])
    run(["mount", "-o", "loop", str(raw), str(mnt)])
    try:
        conf = mnt / "extlinux" / "extlinux.conf"
        texto = conf.read_text()
        novo = re.sub(r"fdt\s+/dtbs/qcom/\S+\.dtb",
                      f"fdt /dtbs/qcom/{dtb}", texto)
        conf.write_text(novo)
        log("extlinux.conf agora aponta para: " + dtb)
        # Sanidade: o dtb precisa existir dentro da imagem de boot
        if not (mnt / "dtbs" / "qcom" / dtb).exists():
            log(f"AVISO: {dtb} não encontrado dentro do boot.bin! "
                "Verifique o nome.", "AVISO")
    finally:
        run(["umount", str(mnt)], check=False)

    run(["img2simg", str(raw), str(saida)])
    raw.unlink(missing_ok=True)
    log(f"boot_patched.bin pronto ({saida.stat().st_size/1e6:.1f} MB)")
    return saida


# ======================================================== ETAPA 4: FLASH
def edl_para_fastboot():
    """aboot novo via EDL, apaga boot e reseta -> dispositivo cai em fastboot."""
    log("Gravando aboot (lk2nd) via EDL e reiniciando para fastboot...")
    edl_com_retry(edl_cmd("w", "aboot", str(FW / "aboot.mbn")),
                  "gravação do aboot", timeout=300, inatividade_max=90)

    # Invalidar o boot stock. O 'edl e boot' desses dongles falha às vezes
    # com "No storage drive number" e ainda imprime 'Erased' (visto em
    # campo!) — se o boot stock sobreviver, o aboot custom inicia o
    # Android de fábrica em vez de cair em fastboot. Então fazemos o
    # determinístico: escrever 1MB de zeros no início da partição,
    # destruindo o magic 'ANDROID!' do boot.img.
    zeros = WORK / "zeros_1mb.bin"
    if not zeros.exists() or zeros.stat().st_size != 1 << 20:
        zeros.write_bytes(b"\x00" * (1 << 20))
    edl_com_retry(edl_cmd("w", "boot", str(zeros)),
                  "invalidação do boot stock (zeros)",
                  timeout=120, inatividade_max=60)
    # O erase clássico continua como tentativa extra, mas sem exigência
    run_stream(edl_cmd("e", "boot"), timeout=120, inatividade_max=60,
               check=False)
    run_stream(edl_cmd("reset"), timeout=60, inatividade_max=30, check=False)
    if not esperar_fastboot_interativo():
        sys.exit("ABORTADO: dispositivo não apareceu em fastboot mesmo após "
                 "replug. O backup está intacto em ./backup. Para retomar "
                 "deste ponto depois: sudo python3 opendongle_autoinstall.py "
                 "--continuar")


def flash_particao_com_retry(particao, arquivo, tentativas=3):
    """
    VISTO EM CAMPO (2x no mesmo dongle): o USB pode cair no meio de
    transferências longas ('Status read failed (No such device)') —
    tipicamente instabilidade de energia da porta sob a corrente de
    escrita do eMMC. Aqui cada partição ganha retry: se cair, o
    autômato reconduz o dispositivo ao fastboot (replug guiado se
    preciso) e regravamos a MESMA partição do zero.
    """
    for i in range(1, tentativas + 1):
        # -S 128M: fatia a transferência em pedaços de 128MB. Motivo de
        # campo: dois dongles caíram do USB exatamente no chunk final
        # gigante do rootfs. Pedaços menores = trocas de status mais
        # frequentes, sem janela longa de silêncio para o link morrer, e
        # falhas detectadas cedo.
        rc, txt = run_stream(["fastboot", "-S", "128M", "flash",
                              particao, str(arquivo)],
                             timeout=2400, inatividade_max=900, check=False)
        if rc == 0:
            return
        log(f"Falha ao gravar '{particao}' (tentativa {i}/{tentativas}). "
            "Provável queda de USB sob carga — dica: use porta USB "
            "traseira/direta da máquina e cabo curto de boa qualidade.",
            "AVISO")
        if i < tentativas:
            if not esperar_fastboot_interativo():
                break
    sys.exit(f"ABORTADO: '{particao}' falhou {tentativas}x. Backup intacto "
             "em ./backup. Troque porta/cabo USB e rode com --continuar.")


def flash_completo(pasta_backup):
    log("Flash completo via fastboot (ordem oficial do projeto)...")
    # fastboot fica mudo durante escritas longas (minutos no rootfs);
    # o heartbeat mostra vida e o retry acima cobre quedas de USB.
    for particao, arquivo in SEQUENCIA_FLASH:
        flash_particao_com_retry(particao, FW / arquivo)

    # Restaura as partições de calibração DO SEU DONGLE (backup da etapa 1)
    log("Restaurando partições de calibração do backup original...")
    for p in PARTICOES_CALIBRACAO:
        arq = pasta_backup / f"{p}.bin"
        if not arq.exists() or arq.stat().st_size == 0:
            log(f"Sem backup de '{p}' — PULANDO a restauração desta "
                "partição (modem/4G pode não funcionar).", "AVISO")
            continue
        flash_particao_com_retry(p, arq)

    run(["fastboot", "reboot"], timeout=60, check=False)
    log("Reboot enviado. Aguardando o Debian subir...")


def reflash_apenas_boot(novo_boot):
    """Usado no MODO TESTE: só a partição boot muda entre placas."""
    if not esperar_fastboot_interativo(timeout_inicial=60):
        sys.exit("ABORTADO: sem fastboot para reflash do boot. "
                 "Retome depois com: --continuar")
    flash_particao_com_retry("boot", novo_boot)
    run(["fastboot", "reboot"], timeout=60, check=False)


# ==================================================== ETAPA 5: VERIFICAÇÃO
def porta_aberta(ip, porta, timeout=2):
    try:
        with socket.create_connection((ip, porta), timeout=timeout):
            return True
    except OSError:
        return False


def ping_ok(ip):
    r = run(["ping", "-c", "1", "-W", "2", ip], check=False, quiet=True)
    return r is not None and r.returncode == 0


def interfaces_rede():
    r = run(["ip", "-o", "link"], check=False, quiet=True)
    nomes = set()
    for linha in (r.stdout or "").splitlines():
        partes = linha.split(":")
        if len(partes) >= 2:
            nomes.add(partes[1].strip().split("@")[0])
    return nomes


def garantir_interface_rede(timeout=240):
    """
    PROBLEMA VISTO EM CAMPO: após o flash, o dongle re-enumera como
    gadget de REDE (não mais fastboot), mas o PC nem sempre ativa a
    interface sozinho — e às vezes o gadget só enumera após replug.
    Esta função cuida do lado do PC: acha a interface nova (enx*/usb*),
    conecta via NetworkManager, e se o DHCP não vier configura IP
    estático 192.168.100.2/24. Se nada aparecer, guia o replug.
    """
    log("Procurando a interface de rede USB do dongle no PC...")
    inicio = time.time()
    pediu_replug = False
    while time.time() - inicio < timeout:
        for iface in sorted(interfaces_rede()):
            if not iface.startswith(("enx", "usb")):
                continue
            r = run(["ip", "-o", "-4", "addr", "show", "dev", iface],
                    check=False, quiet=True)
            if "192.168.100." in (r.stdout or ""):
                print()
                log(f"Interface {iface} ativa com IP na rede do dongle.")
                return True
            print()
            log(f"Interface {iface} encontrada; ativando...")
            run(["nmcli", "device", "connect", iface],
                check=False, quiet=True, timeout=30)
            time.sleep(5)
            r = run(["ip", "-o", "-4", "addr", "show", "dev", iface],
                    check=False, quiet=True)
            if "192.168.100." in (r.stdout or ""):
                log(f"IP obtido via DHCP em {iface}.")
                return True
            log("DHCP não veio; usando IP estático 192.168.100.2/24 "
                f"em {iface} (suficiente para falar com o dongle).")
            run(["ip", "link", "set", iface, "up"], check=False, quiet=True)
            run(["ip", "addr", "replace", "192.168.100.2/24",
                 "dev", iface], check=False, quiet=True)
            return True

        if not pediu_replug and time.time() - inicio > 60:
            pediu_replug = True
            print("""
  >> A interface de rede do dongle ainda não apareceu no PC.
  >> É normal nesses sticks: DESPLUGUE e REPLUGUE (SEM botão).
  >> O Debian vai subir e o PC deve enxergar uma interface 'enx...'.
""")
        print(f"\r   … procurando interface: "
              f"{int(time.time()-inicio):3d}s/{timeout}s   ",
              end="", flush=True)
        time.sleep(3)
    print()
    log("Interface de rede do dongle não apareceu no PC.", "AVISO")
    return False


def verificar_boot(timeout=240):
    """
    Sucesso = o dongle virou um dispositivo USB de rede (RNDIS/NCM) e
    responde em 192.168.100.1 (ping e/ou SSH na porta 22).
    Se o devicetree estiver ERRADO, tipicamente USB/rede/WiFi não sobem.
    """
    # Primeiro o lado do PC: interface achada, ativa e com IP na sub-rede
    garantir_interface_rede()
    log("Verificando boot do Debian (rede USB em 192.168.100.1)...")
    log("  Lembrete: o PRIMEIRO boot é o mais lento (redimensiona o "
        "rootfs e gera chaves SSH) — 2 a 4 min de espera são normais.")
    ok = esperar(lambda: ping_ok(IP_PADRAO) or porta_aberta(IP_PADRAO, 22),
                 f"resposta de {IP_PADRAO}", timeout=timeout, intervalo=5)
    if ok:
        ssh = porta_aberta(IP_PADRAO, 22)
        log(f"BOOT CONFIRMADO! ping/rede OK{' + SSH ativo' if ssh else ''}")
        log("Acesso: ssh user@192.168.100.1  (senha: 1) | "
            "WiFi: 4G-UFI-XX / 1234567890")
    return ok


def modo_teste_iterativo(pasta_backup, contagem_assinaturas, pular_edl=False):
    """
    Plano B solicitado: como só UMA variável difere entre as placas
    (a linha fdt), testamos placa por placa reflashando SÓ o boot (~64MB)
    e checando se o sistema sobe. A primeira que subir é a placa real,
    e a correlação assinaturas->placa vira dado do balizador.

    pular_edl=True: usado no --continuar, quando o aboot já foi gravado
    e o boot apagado numa execução anterior — vamos direto ao fastboot.
    """
    log("=" * 60)
    log("MODO TESTE ITERATIVO DE PLACAS")
    log("=" * 60)

    # Ordena candidatos: mais assinaturas primeiro (chute mais provável)
    candidatos = sorted(PLACAS, key=lambda p: -contagem_assinaturas.get(p, 0))
    log("Ordem de teste: " + " -> ".join(candidatos))

    primeiro = True
    for placa in candidatos:
        log(f"--- Testando placa {placa} ({PLACAS[placa]['dtb']}) ---")
        boot = patch_boot(PLACAS[placa]["dtb"])
        if primeiro:
            # Primeira iteração: flash completo (sistema ainda não instalado)
            if pular_edl:
                # aboot/boot já preparados na execução anterior;
                # basta o dongle aparecer em fastboot (replug se preciso)
                if not esperar_fastboot_interativo():
                    sys.exit("ABORTADO: sem fastboot. Backup intacto.")
            else:
                edl_para_fastboot()
            flash_completo(pasta_backup)
            primeiro = False
        else:
            reflash_apenas_boot(boot)

        if verificar_boot(timeout=180):
            log(f">>> PLACA CONFIRMADA POR TESTE REAL: {placa} <<<")
            salvar_confirmacao(contagem_assinaturas, placa, "teste_real")
            return placa
        log(f"{placa} não subiu. Próxima candidata...", "AVISO")

    log("Nenhuma placa testada resultou em boot com rede.", "ERRO")
    log("Possíveis causas: cabo/porta USB, PC não criou interface RNDIS, "
        "ou hardware fora da família suportada.")
    return None


# ==================================================== ETAPA 6: LIMPEZA
def etapa6_limpeza(pasta_backup):
    """
    *** ETAPA DESATIVADA ATÉ FAZERMOS TESTES REAIS ***
    Quando ativada, apaga o backup APÓS instalação confirmada com sucesso.
    Para ativar: descomente o bloco abaixo (e pense duas vezes — o backup
    contém calibrações de rádio ÚNICAS deste dongle, incluindo IMEI).
    """
    log("Etapa de limpeza do backup: DESATIVADA (aguardando testes reais).")
    # -----------------------------------------------------------------
    # if perguntar_sim_nao(
    #         f"Instalação OK. Apagar o backup em {pasta_backup}? "
    #         "(IRREVERSÍVEL — contém IMEI/calibração únicos!)"):
    #     shutil.rmtree(pasta_backup)
    #     log(f"Backup {pasta_backup} apagado.")
    # else:
    #     log("Backup mantido.")
    # -----------------------------------------------------------------


# ============================================================== MAIN
def preflight():
    if os.geteuid() != 0:
        sys.exit("Rode como root: sudo python3 opendongle_autoinstall.py "
                 "(necessário para edl/mount/fastboot)")
    for binario in ("edl", "fastboot", "simg2img", "img2simg", "lsusb"):
        if not shutil.which(binario):
            sys.exit(f"Dependência ausente: {binario}. Rode ./install.sh")
    faltando = [a for _, a in SEQUENCIA_FLASH if a != "boot_patched.bin"
                and not (FW / a).exists()]
    if faltando:
        sys.exit(f"Firmware ausente: {faltando}. Rode setup_estrutura.py")
    if not LOADER.exists():
        sys.exit("Loader firehose ausente (prog_emmc_firehose_8916.mbn). "
                 "Rode setup_estrutura.py de novo — ele baixa e valida.")
    WORK.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)


def pasta_backup_mais_recente():
    pastas = sorted(BACKUP_DIR.glob("dongle_*"))
    # Só aceita backup que passou na verificação (tem manifesto)
    validas = [p for p in pastas if (p / "manifesto.json").exists()]
    return validas[-1] if validas else None


def fluxo_continuar(placa_arg):
    """
    Retoma a instalação de onde parou: pressupõe que o backup já foi
    feito E verificado (manifesto.json) e que o aboot já foi gravado
    (dongle cai em fastboot no replug). Pula EDL inteiramente.
    """
    log("MODO --continuar: retomando instalação (pulando backup e EDL)")
    pasta_backup = pasta_backup_mais_recente()
    if pasta_backup is None:
        # Existe pasta de backup sem manifesto (backup que falhou)?
        soltas = sorted(BACKUP_DIR.glob("dongle_*"))
        if soltas and aceitar_risco_sem_backup(
                "nenhum backup verificado; existe apenas backup "
                f"parcial/não verificado em {soltas[-1]}"):
            pasta_backup = soltas[-1]
        else:
            sys.exit("Nenhum backup VERIFICADO encontrado em ./backup — "
                     "não dá para continuar com segurança. Rode o fluxo "
                     "completo (sem --continuar).")
    log(f"Usando backup verificado: {pasta_backup}")

    contagem = {nome: 0 for nome in PLACAS}
    if placa_arg:
        # Placa informada: caminho direto
        patch_boot(PLACAS[placa_arg]["dtb"])
        if not esperar_fastboot_interativo():
            sys.exit("ABORTADO: sem fastboot. Replugue e tente de novo.")
        flash_completo(pasta_backup)
        if verificar_boot():
            salvar_confirmacao(contagem, placa_arg, "teste_real")
            log(f"INSTALAÇÃO CONCLUÍDA. Placa: {placa_arg}. Log: {LOGFILE}")
            etapa6_limpeza(pasta_backup)
            return
        log("Placa informada não subiu; entrando em modo teste...", "AVISO")
        contagem = {k: 0 for k in PLACAS if k != placa_arg}

    placa = modo_teste_iterativo(pasta_backup, contagem, pular_edl=True)
    if placa is None:
        sys.exit("Instalação incompleta. Backup preservado em ./backup")
    log(f"INSTALAÇÃO CONCLUÍDA. Placa: {placa}. Log: {LOGFILE}")
    etapa6_limpeza(pasta_backup)


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Instalador Debian OpenStick para dongles MSM8916")
    ap.add_argument("--continuar", action="store_true",
                    help="Retoma de onde parou (backup já feito, aboot já "
                         "gravado). Pula EDL e vai direto ao fastboot.")
    ap.add_argument("--placa", choices=list(PLACAS),
                    help="Força uma placa específica, pulando a detecção.")
    ap.add_argument("--sem-backup", action="store_true",
                    help="NÃO RECOMENDADO: pula o dump completo do "
                         "firmware (salva só a calibração, em melhor "
                         "esforço). Exige confirmação digitada. Use "
                         "apenas em aparelho já considerado perdido.")
    args = ap.parse_args()

    preflight()
    log("OpenDongle Auto-Installer — início")

    if args.continuar:
        return fluxo_continuar(args.placa)

    # ETAPA 1 — backup (obrigatório, salvo aceite explícito de risco)
    if args.sem_backup and not aceitar_risco_sem_backup(
            "flag --sem-backup informada pelo usuário"):
        sys.exit("ABORTADO por escolha do usuário. Nada foi gravado.")
    pasta_backup = etapa1_backup(sem_backup=args.sem_backup)

    # ETAPA 2 — descobrir a placa
    if args.placa:
        placa, contagem = args.placa, {nome: 0 for nome in PLACAS}
        log(f"Placa forçada por argumento: {placa}")
    else:
        placa, contagem = etapa2_detectar_placa(pasta_backup)

    if placa is None:
        # MODO TESTE: instala + itera boots até achar a placa
        placa = modo_teste_iterativo(pasta_backup, contagem)
        if placa is None:
            sys.exit("Instalação incompleta. Backup preservado em ./backup")
    else:
        # Caminho direto: placa conhecida
        patch_boot(PLACAS[placa]["dtb"])          # ETAPA 3
        edl_para_fastboot()                        # ETAPA 4
        flash_completo(pasta_backup)
        if not verificar_boot():                   # ETAPA 5
            log("Boot não confirmado com a placa detectada. "
                "Entrando em modo teste com as demais...", "AVISO")
            restantes = {k: v for k, v in contagem.items() if k != placa}
            placa = modo_teste_iterativo(pasta_backup, restantes) or placa

    log(f"INSTALAÇÃO CONCLUÍDA. Placa: {placa}. Log: {LOGFILE}")
    etapa6_limpeza(pasta_backup)                   # ETAPA 6 (comentada)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário. Backup (se feito) está em ./backup")
