#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_estrutura.py — Prepara todo o ambiente do OpenStick Auto-Installer
=========================================================================
O que este script faz:
  1. Cria a estrutura de pastas (firmware/, backup/, logs/, work/)
  2. Baixa o openstick-debian.zip do release v1.2 (com retomada de download)
  3. Extrai e valida os 8 arquivos de firmware necessários
  4. Verifica dependências do sistema (edl, fastboot, simg2img...)
  5. Se faltar algo, manda rodar o install.sh (que acompanha o projeto)

Uso:
  python3 setup_estrutura.py
"""

import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

# ---------------------------------------------------------------- constantes
BASE = Path(__file__).resolve().parent
DIRS = ["firmware", "backup", "logs", "work"]

RELEASE_URL = ("https://github.com/LongQT-sea/OpenStick-Builder/"
               "releases/download/v1.2/openstick-debian.zip")
ZIP_PATH = BASE / "work" / "openstick-debian.zip"
ZIP_SIZE_ESPERADO = 150_137_574  # bytes, informado pela API do GitHub

# Arquivos que PRECISAM existir em firmware/ ao final
ARQUIVOS_FIRMWARE = [
    "gpt_both0.bin", "aboot.mbn", "hyp.mbn", "rpm.mbn",
    "sbl1.mbn", "tz.mbn", "boot.bin", "rootfs.bin",
]

# Loader firehose genérico do MSM8916 — necessário porque os dongles zhihe
# usam a chave de teste da Qualcomm (PK_HASH cc3153a8...) com OEM_ID 0x0000,
# combinação que não existe no banco automático do edl. Sem esse arquivo o
# edl para em "Couldn't find a loader for given hwid and pkhash".
LOADER_URL = ("https://raw.githubusercontent.com/OneLabsTools/Programmers/"
              "master/prog_emmc_firehose_8916.mbn")
LOADER_NOME = "prog_emmc_firehose_8916.mbn"
LOADER_SHA256 = "959439aa5864685999b713c3ed12ad5fa408149648b670a9a9ef77bcc9dcab14"
LOADER_BYTES = 93288

# Binários de sistema necessários para o instalador
DEPENDENCIAS = {
    "edl":      "EDL (bkerler/edl) — instale com ./install.sh",
    "fastboot": "pacote 'fastboot' — instale com ./install.sh",
    "simg2img": "pacote 'android-sdk-libsparse-utils' — instale com ./install.sh",
    "img2simg": "pacote 'android-sdk-libsparse-utils' — instale com ./install.sh",
    "lsusb":    "pacote 'usbutils' — instale com ./install.sh",
}


def criar_pastas():
    print("== [1/5] Criando estrutura de pastas ==")
    for d in DIRS:
        (BASE / d).mkdir(exist_ok=True)
        print(f"   ok: {d}/")


def baixar_release():
    print("\n== [2/5] Baixando release v1.2 (~143 MB) ==")
    if ZIP_PATH.exists() and ZIP_PATH.stat().st_size == ZIP_SIZE_ESPERADO:
        print("   zip já baixado e com tamanho correto, pulando download.")
        return

    # Download com suporte a retomada (Range) — útil em conexão instável
    modo = "ab" if ZIP_PATH.exists() else "wb"
    ja_tem = ZIP_PATH.stat().st_size if ZIP_PATH.exists() else 0
    req = urllib.request.Request(RELEASE_URL)
    if ja_tem:
        req.add_header("Range", f"bytes={ja_tem}-")
        print(f"   retomando download a partir de {ja_tem/1e6:.1f} MB")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(ZIP_PATH, modo) as f:
            total = ja_tem
            while True:
                chunk = resp.read(1 << 20)  # 1 MB
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
                pct = 100 * total / ZIP_SIZE_ESPERADO
                print(f"\r   {total/1e6:7.1f} MB ({pct:5.1f}%)", end="", flush=True)
        print()
    except Exception as e:
        sys.exit(f"\n   ERRO no download: {e}\n"
                 f"   Rode o script de novo para retomar de onde parou.")

    if ZIP_PATH.stat().st_size != ZIP_SIZE_ESPERADO:
        sys.exit("   ERRO: tamanho do zip não bate com o esperado. "
                 "Apague work/openstick-debian.zip e baixe de novo.")


def extrair():
    print("\n== [3/5] Extraindo firmware ==")
    fw = BASE / "firmware"
    with zipfile.ZipFile(ZIP_PATH) as z:
        # Testa integridade do zip antes de extrair
        ruim = z.testzip()
        if ruim:
            sys.exit(f"   ERRO: zip corrompido em '{ruim}'. Apague e baixe de novo.")
        for info in z.infolist():
            nome = Path(info.filename).name
            if nome in ARQUIVOS_FIRMWARE:
                with z.open(info) as src, open(fw / nome, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                print(f"   ok: firmware/{nome} "
                      f"({(fw / nome).stat().st_size/1e6:.1f} MB)")

    faltando = [a for a in ARQUIVOS_FIRMWARE if not (fw / a).exists()]
    if faltando:
        sys.exit(f"   ERRO: arquivos ausentes no zip: {faltando}")

    # Gera manifesto sha256 para auditoria futura
    with open(fw / "SHA256SUMS.txt", "w") as m:
        for a in ARQUIVOS_FIRMWARE:
            h = hashlib.sha256((fw / a).read_bytes()).hexdigest()
            m.write(f"{h}  {a}\n")
    print("   ok: firmware/SHA256SUMS.txt gerado")


def baixar_loader():
    print("\n== [4/5] Baixando loader firehose do MSM8916 ==")
    destino = BASE / "firmware" / LOADER_NOME
    if destino.exists() and \
       hashlib.sha256(destino.read_bytes()).hexdigest() == LOADER_SHA256:
        print("   loader já presente e íntegro, pulando.")
        return
    try:
        urllib.request.urlretrieve(LOADER_URL, destino)
    except Exception as e:
        sys.exit(f"   ERRO ao baixar o loader: {e}")
    dados = destino.read_bytes()
    if hashlib.sha256(dados).hexdigest() != LOADER_SHA256:
        destino.unlink()
        sys.exit("   ERRO: sha256 do loader não confere — download "
                 "corrompido ou arquivo alterado na origem. Abortando "
                 "por segurança (esse binário roda DENTRO do chip).")
    if not dados.startswith(b"\x7fELF"):
        destino.unlink()
        sys.exit("   ERRO: loader baixado não é um ELF válido.")
    print(f"   ok: firmware/{LOADER_NOME} ({len(dados)} bytes, sha256 OK)")


def checar_dependencias():
    print("\n== [5/5] Checando dependências ==")
    faltando = []
    for binario, dica in DEPENDENCIAS.items():
        if shutil.which(binario):
            print(f"   ok: {binario}")
        else:
            print(f"   FALTA: {binario}  ->  {dica}")
            faltando.append(binario)
    if faltando:
        print("\n   Rode:  sudo ./install.sh   e depois execute este setup de novo.")
    else:
        print("\nTudo pronto! Próximo passo:")
        print("   sudo python3 opendongle_autoinstall.py")


if __name__ == "__main__":
    criar_pastas()
    baixar_release()
    extrair()
    baixar_loader()
    checar_dependencias()
