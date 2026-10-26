#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
restaurar_backup.py — Restaura o dongle 100% ao firmware original de fábrica
=============================================================================
Escreve o dump completo (orig_fw.bin) de volta na flash via EDL, byte a
byte, incluindo a tabela de partições stock, bootloaders, Android, modem
e calibrações. É o desfazer total da instalação do OpenStick.

Uso:
  sudo python3 restaurar_backup.py                # acha o backup DESTE dongle
  sudo python3 restaurar_backup.py --pasta backup/dongle_20260706_021558
  sudo python3 restaurar_backup.py --so-calibracao   # só fsc/fsg/modem/...
                                                     # (via fastboot, para
                                                     # manter o OpenStick)

Antes de escrever, o script confere o sha256 do orig_fw.bin contra o
manifesto gerado na hora do backup — não restauramos um arquivo corrompido.
E confere que o backup é DESTE dongle pelo serial do chip (EDL): gravar o de outro aparelho
clona ou zera o IMEI. Em fastboot (--so-calibracao) não dá para ler o
aparelho; com backups de mais de um dongle na pasta, --pasta é obrigatório.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'core'))


import argparse
import json
import sys
import time
from pathlib import Path

# Reaproveita a infraestrutura já testada do instalador (mesma pasta)
from opendongle_autoinstall import (
    log, run, run_stream, esperar, sha256_arquivo,
    dispositivo_em_edl, dispositivo_em_fastboot,
    matar_processos_conflitantes, diagnosticar_saida_edl,
    edl_cmd, edl_com_retry, LOADER, PARTICOES_CALIBRACAO, WORK,
    PARTICOES_IDENTIDADE, escolher_backup, serial_edl_do_texto,
)


def identidade_edl():
    """Identidade do aparelho em EDL: o serial do chip (o que vale) e, como
    conferência extra, o sha256 de sec e fsg."""
    WORK.mkdir(exist_ok=True)
    texto = edl_com_retry(edl_cmd("printgpt"), "leitura do serial do chip (identidade)",
                          timeout=120, inatividade_max=60)
    ident = {"serial_edl": serial_edl_do_texto(texto)}
    if not ident["serial_edl"]:
        log("Não li o serial do chip na saída do edl: a escolha do backup "
            "vai exigir --pasta.", "AVISO")
    for p in PARTICOES_IDENTIDADE:
        destino = WORK / f"identidade_{p}.bin"
        destino.unlink(missing_ok=True)
        edl_com_retry(edl_cmd("r", p, str(destino)),
                      f"leitura da partição {p} (identidade)",
                      timeout=300, inatividade_max=120)
        if not destino.exists():
            sys.exit(f"ABORTADO: não consegui ler '{p}' do aparelho.")
        ident[p] = sha256_arquivo(destino)
        destino.unlink()
    return ident


def conferir_integridade(pasta, arquivos):
    """sha256 de cada arquivo contra o manifesto do dia do backup."""
    manifesto = json.loads((pasta / "manifesto.json").read_text())
    log("Conferindo integridade do backup contra o manifesto...")
    for nome in arquivos:
        arq = pasta / nome
        if not arq.exists():
            sys.exit(f"ABORTADO: {nome} não existe no backup.")
        esperado = manifesto["arquivos"].get(nome, {}).get("sha256")
        if not esperado:
            sys.exit(f"ABORTADO: {nome} não consta no manifesto.")
        log(f"   hash de {nome} ({arq.stat().st_size/1e6:.0f} MB)...")
        if sha256_arquivo(arq) != esperado:
            sys.exit(f"ABORTADO: sha256 de {nome} NÃO CONFERE com o "
                     "manifesto — arquivo corrompido, restaurar seria "
                     "gravar lixo no dongle.")
    log("Integridade OK — os arquivos estão exatamente como no dia do backup.")


def restaurar_total(pasta):
    """Reescreve a flash inteira via EDL: volta total ao estado de fábrica."""
    print("""
  RESTAURAÇÃO TOTAL — o dongle voltará 100% ao firmware de fábrica.
  Coloque-o em modo EDL: desplugue e replugue SEGURANDO O BOTÃO.
  (lsusb deve mostrar 05c6:9008)
""")
    matar_processos_conflitantes()
    if not esperar(dispositivo_em_edl, "dispositivo em modo EDL",
                   timeout=300, intervalo=2):
        sys.exit("ABORTADO: dispositivo não apareceu em EDL.")

    # Antes de gravar 4 GB: o backup é mesmo deste aparelho?
    log("Lendo a identidade do aparelho (serial do chip, sec/fsg)...")
    pasta = escolher_backup(pasta, identidade_edl(), preferir_fabrica=True)
    log(f"Backup deste dongle: {pasta}")
    conferir_integridade(pasta, ["orig_fw.bin"])

    total = pasta / "orig_fw.bin"
    log(f"Escrevendo a flash completa de volta ({total.stat().st_size/1e9:.2f} GB).")
    log("  Escrita é mais lenta que leitura: conte com 20 a 60 minutos. "
        "O progresso do edl aparece abaixo.")
    edl_com_retry(edl_cmd("wf", str(total)), "restauração total da flash",
                  timeout=10800, inatividade_max=600)
    run_stream(edl_cmd("reset"), timeout=60, inatividade_max=30, check=False)
    log("RESTAURAÇÃO CONCLUÍDA. Desplugue e replugue sem botão — o "
        "Android de fábrica deve subir como se nada tivesse acontecido.")


def restaurar_calibracao(pasta):
    """Regrava só as partições de calibração via fastboot — para quando o
    OpenStick está instalado mas o modem/rádio precisa dos dados originais."""
    conferir_integridade(pasta, [f"{p}.bin" for p in PARTICOES_CALIBRACAO])
    print("\n  O dongle precisa estar em FASTBOOT para este modo.\n")
    if not esperar(dispositivo_em_fastboot, "dispositivo em fastboot",
                   timeout=300, intervalo=3):
        sys.exit("ABORTADO: sem fastboot.")
    for p in PARTICOES_CALIBRACAO:
        rc, _ = run_stream(["fastboot", "flash", p, str(pasta / f"{p}.bin")],
                           timeout=600, inatividade_max=300, check=False)
        if rc != 0:
            sys.exit(f"ABORTADO: falha ao restaurar '{p}'.")
    run_stream(["fastboot", "reboot"], timeout=60, inatividade_max=30,
               check=False)
    log("Calibração restaurada e reboot enviado.")


def main():
    ap = argparse.ArgumentParser(
        description="Restaura o dongle ao firmware original (via backup)")
    ap.add_argument("--pasta", help="Pasta do backup (padrão: o deste dongle)")
    ap.add_argument("--so-calibracao", action="store_true",
                    help="Restaura apenas fsc/fsg/modem/modemst1/modemst2/"
                         "persist/sec via fastboot (mantém o OpenStick)")
    args = ap.parse_args()

    if not LOADER.exists():
        sys.exit("Loader firehose ausente. Rode setup_estrutura.py")

    if args.so_calibracao:
        pasta = escolher_backup(args.pasta)
        log(f"Usando backup: {pasta}")
        restaurar_calibracao(pasta)
    else:
        # a escolha final acontece com o aparelho em EDL, lendo o serial do chip
        restaurar_total(args.pasta)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompido. O backup permanece intacto em ./backup")
