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
  sudo opendongle diagnostico
  sudo opendongle recursos
  sudo opendongle config show|aplicar
  sudo opendongle backup > backup.json
  sudo opendongle restaurar backup.json
  sudo opendongle reset
  sudo opendongle rede migrar|confirmar|reverter
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opendongle_engine as eng
import opendongle_diag as diag


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
        if "mudou" in res:
            print("  alterado: " + (", ".join(res["mudou"]) or "nada (já estava aplicado)"))
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

    sub.add_parser("diagnostico",
                   help="testa áudio, Bluetooth, vídeo USB e modem 4G")

    sub.add_parser("recursos", help="RAM usada por serviço")

    p = sub.add_parser("config", help="mostra ou aplica a config central")
    p.add_argument("acao", choices=["show", "aplicar"])

    sub.add_parser("backup", help="imprime a config (redirecione pra um arquivo)")

    p = sub.add_parser("restaurar", help="restaura e aplica um backup")
    p.add_argument("arquivo")

    sub.add_parser("reset", help="volta à configuração de fábrica")

    p = sub.add_parser("rede", help="migra a rede pro systemd-networkd, "
                       "confirma ou reverte a última mudança de rede")
    p.add_argument("acao", choices=["migrar", "confirmar", "reverter"])

    args = ap.parse_args()
    precisa_root()

    if args.cmd == "backup":
        res = eng.backup()
        if not res["ok"]:
            sys.exit("✗ " + res["erro"])
        print(res["backup"])
        return
    if args.cmd == "config" and args.acao == "show" and not args.json:
        res = eng.config_show()
        if not res["ok"]:
            sys.exit("✗ " + res["erro"])
        print(json.dumps(res["config"], ensure_ascii=False, indent=2))
        return

    if args.cmd == "recursos":
        res = eng.recursos()
        if args.json:
            print(json.dumps(res, ensure_ascii=False))
            return
        print(f"RAM disponível: {res['ram_disponivel_kb'] // 1024} MB "
              f"de {res['ram_total_kb'] // 1024} MB  (métrica: {res['metrica']})")
        total = 0
        for s in res["servicos"]:
            total += s["kb"]
            if s["kb"] >= 512:
                print(f"  {s['kb'] / 1024:6.1f} MB  {s['unit']}")
        print(f"  {total / 1024:6.1f} MB  TOTAL em processos")
        return

    if args.cmd == "diagnostico":
        resultados = diag.rodar_tudo()
        if args.json:
            print(json.dumps(resultados, ensure_ascii=False))
        else:
            diag.imprimir_relatorio(resultados)
        sys.exit(0 if all(r["status"] != "falha" for r in resultados) else 1)

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
    elif args.cmd == "config":
        res = eng.config_show() if args.acao == "show" else eng.config_aplicar()
    elif args.cmd == "restaurar":
        try:
            with open(args.arquivo) as f:
                texto = f.read()
        except OSError as e:
            sys.exit(f"✗ não consegui ler {args.arquivo}: {e}")
        res = eng.restaurar(texto)
    elif args.cmd == "rede":
        res = eng.executar(f"rede-{args.acao}", {})
    elif args.cmd == "reset":
        if input("Voltar à configuração de fábrica? Digite 'sim': ").strip() != "sim":
            sys.exit("Cancelado.")
        res = eng.reset()
    else:
        ap.error("comando desconhecido")

    imprime(res, cru=args.json)


if __name__ == "__main__":
    main()
