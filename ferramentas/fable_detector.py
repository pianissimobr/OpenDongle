#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fable_detector.py — Camada DETECTOR do projeto Fable
=====================================================
Sonda QUALQUER dispositivo Qualcomm em modo EDL, identifica o SoC pelo
HWID, encontra o loader (firehose) compatível, e extrai a inteligência
que as camadas seguintes (Extractor → Parts Bank → Builder) vão usar
para portar Linux.

Diferente do instalador OpenStick (que assume MSM8916 + loader fixo),
aqui NADA é assumido: o chip, o loader e o layout são DESCOBERTOS.

Filosofia de segurança: o Detector é READ-ONLY por padrão. Ele nunca
escreve na flash — só lê, identifica e relata. Escrever é trabalho das
camadas de cima, com backup e confirmação.

Uso:
  python3 fable_detector.py                 # sonda e gera relatório
  python3 fable_detector.py --dump          # + dump completo (se couber)
  python3 fable_detector.py --loaders-dir /caminho/Loaders
"""

import argparse
import datetime
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "fable_out"

# Mapa MSM_ID -> família de SoC. O MSM_ID vem nos 4 primeiros bytes do
# HWID (ex.: 0x007050e1 -> msm8916). Fonte: convenção de HWID Qualcomm,
# refinada com o banco bkerler. Expandível conforme encontramos aparelhos.
MSM_ID = {
    0x007050e1: ("MSM8916", "arm64", "OpenStick suportado (dongles 4G)"),
    0x009600e1: ("MSM8909", "arm (32-bit)", "Snapdragon 210 — porte NOVO"),
    0x000560e1: ("MSM8917", "arm64", "Snapdragon 425 — porte NOVO"),
    0x0004f0e1: ("MSM8937", "arm64", "Snapdragon 430 — aparentado ao 8917"),
    0x000460e1: ("MSM8953", "arm64", "Snapdragon 625 (Moto G7 alvo!)"),
    0x0006b0e1: ("MSM8940", "arm64", "Snapdragon 435"),
}

# Repos públicos de loaders (só usados se o banco local não casar)
LOADERS_REPO_TREE = ("https://api.github.com/repos/bkerler/Loaders/"
                     "git/trees/main?recursive=1")
LOADERS_RAW = "https://raw.githubusercontent.com/bkerler/Loaders/main/"


def run(cmd, timeout=120):
    print("  $ " + " ".join(str(c) for c in cmd))
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return None


def em_edl():
    r = run(["lsusb"], timeout=15)
    return r is not None and "05c6:9008" in (r.stdout or "")


def sondar_hwid():
    """
    Roda 'edl printgpt' sem loader forçado. Mesmo quando o edl NÃO acha
    loader, o handshake Sahara já imprime HWID/PK_HASH/Serial — que é a
    inteligência que queremos. Parseamos isso da saída.
    """
    print("== Sondando o dispositivo (Sahara handshake)...")
    r = run(["edl", "printgpt"], timeout=120)
    txt = ((r.stdout or "") + (r.stderr or "")) if r else ""
    (OUT / "sahara_raw.txt").write_text(txt)

    info = {}
    m = re.search(r"HWID:\s*(0x[0-9a-fA-F]+)", txt)
    if m:
        info["hwid"] = m.group(1)
    m = re.search(r"MSM_ID:(0x[0-9a-fA-F]+)", txt)
    if m:
        info["msm_id"] = int(m.group(1), 16)
    m = re.search(r"OEM_ID:(0x[0-9a-fA-F]+)", txt)
    if m:
        info["oem_id"] = m.group(1)
    m = re.search(r"PK_HASH:\s*(0x[0-9a-fA-F]+)", txt)
    if m:
        info["pk_hash"] = m.group(1)
    m = re.search(r'CPU detected:\s*"?([A-Za-z0-9]+)"?', txt)
    if m:
        info["cpu_edl"] = m.group(1)
    m = re.search(r"Serial:\s*(0x[0-9a-fA-F]+)", txt)
    if m:
        info["serial"] = m.group(1)
    info["achou_loader"] = "Couldn't find a loader" not in txt
    return info


def identificar(info):
    msm = info.get("msm_id")
    if msm in MSM_ID:
        nome, arch, nota = MSM_ID[msm]
        info.update(soc=nome, arch=arch, nota=nota, conhecido=True)
    else:
        info.update(soc="DESCONHECIDO", arch="?",
                    nota="MSM_ID fora do mapa — investigar", conhecido=False)
    return info


def montar_chave_loader(info):
    """Constrói o prefixo do nome de loader que o bkerler usa:
    <HWID sem 0x, 16 hex><_><pkhash[:16]>. Serve para procurar no banco."""
    hwid = info.get("hwid", "0x0")[2:].rjust(16, "0")[:16]
    pk = info.get("pk_hash", "0x0")[2:][:16]
    return hwid, pk


def procurar_loader_local(info, loaders_dir):
    if not loaders_dir or not Path(loaders_dir).is_dir():
        return None
    hwid, pk = montar_chave_loader(info)
    # Casa por HWID exato; se não, por pkhash (mesmo OEM, HWID próximo)
    candidatos = list(Path(loaders_dir).rglob("*fhprg*")) + \
                 list(Path(loaders_dir).rglob("*.mbn"))
    for c in candidatos:
        if hwid[:8] in c.name and pk[:8] in c.name:
            return c
    for c in candidatos:
        if pk[:12] in c.name:  # mesmo assinante
            return c
    return None


def procurar_loader_online(info):
    """Consulta o índice do repo bkerler e sugere loaders plausíveis
    (não baixa automaticamente — escrever no chip pede decisão humana)."""
    hwid, pk = montar_chave_loader(info)
    r = run(["python3", "-c",
             "import urllib.request,sys;"
             f"print(urllib.request.urlopen('{LOADERS_REPO_TREE}',"
             "timeout=30).read().decode())"], timeout=60)
    if not r or r.returncode != 0:
        return []
    try:
        import json as _j
        paths = [t["path"] for t in _j.loads(r.stdout)["tree"]]
    except Exception:
        return []
    soc = info.get("soc", "").lower()
    sugestoes = []
    for p in paths:
        base = p.split("/")[-1]
        if pk[:12] in base or (soc and soc in p.lower() and "fhprg" in base):
            sugestoes.append(p)
    return sugestoes[:12]


def relatorio(info, loader_local, sugestoes):
    OUT.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    info["timestamp"] = stamp
    info["loader_local"] = str(loader_local) if loader_local else None
    info["loaders_sugeridos"] = sugestoes
    (OUT / "detector_report.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False))

    print("\n" + "=" * 60)
    print("RELATÓRIO DO DETECTOR FABLE")
    print("=" * 60)
    print(f"  HWID:      {info.get('hwid','?')}")
    print(f"  MSM_ID:    {hex(info['msm_id']) if 'msm_id' in info else '?'}")
    print(f"  SoC:       {info.get('soc','?')}  ({info.get('arch','?')})")
    print(f"  PK_HASH:   {info.get('pk_hash','?')[:26]}...")
    print(f"  OEM_ID:    {info.get('oem_id','?')}")
    print(f"  Serial:    {info.get('serial','?')}")
    print(f"  Nota:      {info.get('nota','')}")
    print(f"  edl achou loader sozinho? {'SIM' if info.get('achou_loader') else 'NÃO'}")
    if loader_local:
        print(f"\n  ✅ Loader compatível no banco local:\n     {loader_local}")
        print("     Para dumpar:  edl rf dump.bin "
              f"--loader={loader_local}")
    elif info.get("achou_loader"):
        print("\n  ✅ O edl casa um loader automaticamente — pode dumpar "
              "com:\n     edl rf dump.bin")
    else:
        print("\n  ⚠️  Nenhum loader casado. Candidatos do repo bkerler "
              "(baixe o certo e valide com CUIDADO):")
        for s in sugestoes:
            print(f"     {LOADERS_RAW}{s}")
        if not sugestoes:
            print("     (nenhum candidato óbvio — investigação manual)")

    # Veredito de porte
    print("\n  VEREDITO FABLE:")
    if info.get("soc") == "MSM8916":
        print("     → Território OpenStick. Use o instalador existente.")
    elif info.get("conhecido"):
        print(f"     → {info['soc']}: chip conhecido, porte NOVO. A imagem "
              "OpenStick NÃO serve (kernel/dtb diferentes). Precisa de "
              "rootfs+kernel próprios (postmarketOS é o melhor ponto de "
              "partida para esta família).")
    else:
        print("     → SoC desconhecido: mapear MSM_ID e achar loader "
              "antes de qualquer escrita.")
    print(f"\n  Relatório salvo em: {OUT/'detector_report.json'}")


def main():
    ap = argparse.ArgumentParser(description="Detector Fable (read-only)")
    ap.add_argument("--dump", action="store_true",
                    help="Se um loader casar, faz dump completo read-only")
    ap.add_argument("--loaders-dir",
                    help="Pasta local do repo bkerler/Loaders (opcional)")
    args = ap.parse_args()

    if not shutil.which("edl"):
        sys.exit("edl não encontrado. Rode o install.sh do OpenStick.")
    OUT.mkdir(exist_ok=True)

    print("Coloque o dispositivo em modo EDL (05c6:9008) e conecte.")
    run(["systemctl", "stop", "ModemManager"], timeout=15)
    if not em_edl():
        # espera curta
        import time
        for _ in range(60):
            if em_edl():
                break
            time.sleep(2)
        else:
            sys.exit("Nenhum dispositivo em EDL. Confira cabo/botão/porta.")

    info = identificar(sondar_hwid())
    if "hwid" not in info:
        sys.exit("Não consegui ler o HWID — o Sahara respondeu? Veja "
                 f"{OUT/'sahara_raw.txt'}")

    loader_local = procurar_loader_local(info, args.loaders_dir)
    sugestoes = [] if (loader_local or info.get("achou_loader")) \
        else procurar_loader_online(info)
    relatorio(info, loader_local, sugestoes)

    if args.dump and (loader_local or info.get("achou_loader")):
        print("\n== Dump read-only solicitado...")
        cmd = ["edl", "rf", str(OUT / "dump_completo.bin")]
        if loader_local:
            cmd.append(f"--loader={loader_local}")
        run(cmd, timeout=7200)
        print(f"Dump salvo em {OUT/'dump_completo.bin'} (se bem-sucedido).")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompido. O Detector é read-only — nada foi alterado.")
