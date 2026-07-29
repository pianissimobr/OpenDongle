#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
restaurar_backup.py — Restaura o dongle 100% ao firmware original de fábrica
=============================================================================
Escreve o dump completo (orig_fw.bin) de volta na flash via EDL, byte a
byte, incluindo a tabela de partições stock, bootloaders, Android, modem
e calibrações. É o desfazer total da instalação do OpenStick.

Uso:
  sudo python3 restaurar_backup.py                # usa o backup mais recente
  sudo python3 restaurar_backup.py --pasta backup/dongle_20260706_021558
  sudo python3 restaurar_backup.py --so-calibracao   # só fsc/fsg/modem/...
                                                     # (via fastboot, para
                                                     # manter o OpenStick)

Antes de escrever, o script confere o sha256 do orig_fw.bin contra o
manifesto gerado na hora do backup — não restauramos um arquivo corrompido.
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
    edl_cmd, edl_com_retry, BACKUP_DIR, LOADER, PARTICOES_CALIBRACAO,
)


def achar_pasta(args):
    if args.pasta:
        pasta = Path(args.pasta)
        if not pasta.is_dir():
            sys.exit(f"Pasta não existe: {pasta}")
        return pasta
    pastas = sorted(p for p in BACKUP_DIR.glob("dongle_*")
                    if (p / "manifesto.json").exists())
    if not pastas:
        sys.exit("Nenhum backup verificado encontrado em ./backup")
    return pastas[-1]


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
    conferir_integridade(pasta, ["orig_fw.bin"])
    matar_processos_conflitantes()
    if not esperar(dispositivo_em_edl, "dispositivo em modo EDL",
                   timeout=300, intervalo=2):
        sys.exit("ABORTADO: dispositivo não apareceu em EDL.")

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
    ap.add_argument("--pasta", help="Pasta do backup (padrão: mais recente)")
    ap.add_argument("--so-calibracao", action="store_true",
                    help="Restaura apenas fsc/fsg/modem/modemst1/modemst2/"
                         "persist/sec via fastboot (mantém o OpenStick)")
    args = ap.parse_args()

    if not LOADER.exists():
        sys.exit("Loader firehose ausente. Rode setup_estrutura.py")

    pasta = achar_pasta(args)
    log(f"Usando backup: {pasta}")

    if args.so_calibracao:
        restaurar_calibracao(pasta)
    else:
        restaurar_total(pasta)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompido. O backup permanece intacto em ./backup")
