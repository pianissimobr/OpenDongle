#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongle — CLI de configuração do dongle (casca sobre o motor único)
=======================================================================
Instalado como /usr/local/bin/opendongle. Faz por terminal exatamente
o que o painel web faz, chamando o MESMO motor (opendongle_engine).

  sudo opendongle status
  sudo opendongle hotspot --ssid MinhaRede --senha minhasenha123
  sudo opendongle wifi --ssid CasaDoFulano --senha segredo123
  sudo opendongle wifi --list
  sudo opendongle mode-hotspot
  sudo opendongle senha --nova umaSenhaForte
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opendongle_engine as eng


def precisa_root():
    if os.geteuid() != 0:
        sys.exit("Rode com sudo: sudo opendongle ...")


def imprime(res, cru=False):
    if cru:
        print(json.dumps(res, ensure_ascii=False))
        return
    if not res.get("ok"):
        print("✗ " + res.get("erro", "erro desconhecido"))
        sys.exit(1)
    # impressão amigável por tipo de retorno
    if "modo" in res and "internet" in res:  # status
        net = "conectado à internet" if res["internet"] else \
              "SEM internet (verifique o chip 4G)"
        print(f"Modo:     {res['modo']}")
        print(f"Internet: {net}")
        if res.get("hotspot_ssid"):
            print(f"Hotspot:  {res['hotspot_ssid']}")
    elif "redes" in res:  # list-wifi
        for r in res["redes"]:
            print(f"  {r['sinal']:>3}%  {r['ssid']}  ({r['seg']})")
    else:
        if res.get("ssid"):
            print(f"✓ ok — rede: {res['ssid']}")
        else:
            print("✓ ok")
        if res.get("aviso"):
            print("  ⚠ " + res["aviso"])


def main():
    ap = argparse.ArgumentParser(prog="opendongle",
                                 description="Configuração do OpenDongle")
    ap.add_argument("--json", action="store_true", help="saída crua JSON")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="mostra modo, internet e hotspot")

    p = sub.add_parser("hotspot", help="troca nome/senha do hotspot")
    p.add_argument("--ssid", required=True)
    p.add_argument("--senha", required=True)

    p = sub.add_parser("wifi", help="conecta a um Wi-Fi (ou --list)")
    p.add_argument("--ssid")
    p.add_argument("--senha", default="")
    p.add_argument("--list", action="store_true", help="lista redes")

    sub.add_parser("mode-hotspot", help="volta ao modo ponto de acesso")

    p = sub.add_parser("senha", help="troca a senha de administração")
    p.add_argument("--nova", required=True)

    args = ap.parse_args()
    precisa_root()

    if args.cmd == "status":
        res = eng.status()
    elif args.cmd == "hotspot":
        res = eng.set_hotspot(args.ssid, args.senha)
    elif args.cmd == "wifi":
        res = eng.listar_wifi() if args.list else \
            eng.connect_wifi(args.ssid, args.senha)
    elif args.cmd == "mode-hotspot":
        res = eng.mode_hotspot()
    elif args.cmd == "senha":
        res = eng.set_password(args.nova)
    else:
        ap.error("comando desconhecido")

    imprime(res, cru=args.json)


if __name__ == "__main__":
    main()
