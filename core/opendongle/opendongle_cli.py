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
  sudo opendongle usuario --novo lucas
  sudo opendongle diagnostico
  sudo opendongle recursos
  sudo opendongle config show|aplicar
  sudo opendongle config set lan.dhcp.inicio=20 dns.criptografado=true
  sudo opendongle dhcp clientes|fixar|soltar --mac .. --ip .. --nome ..
  sudo opendongle redir add --nome web --porta-externa 8080 --ip 192.168.100.20 --porta-interna 80
  sudo opendongle logs [opendongle|dnsmasq|hostapd|wifi-cliente|rede|usb-4g]
  sudo opendongle backup > backup.json
  sudo opendongle restaurar backup.json
  sudo opendongle reset
  sudo opendongle rede migrar|confirmar|reverter
  sudo opendongle bluetooth status|buscar|parear MAC|responder sim|conectar MAC
  sudo opendongle usb [host|device]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opendongle_audio as aud
import opendongle_bluetooth as bt
import opendongle_engine as eng
import opendongle_sistema as sis
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

    p = sub.add_parser("usuario", help="troca o nome do usuário de administração")
    p.add_argument("--novo", required=True)

    sub.add_parser("diagnostico",
                   help="testa áudio, Bluetooth, vídeo USB e modem 4G")

    sub.add_parser("recursos", help="RAM usada por serviço")

    p = sub.add_parser("config", help="mostra, altera (set chave=valor) ou "
                       "aplica a config central")
    p.add_argument("acao", choices=["show", "set", "aplicar"])
    p.add_argument("atribuicoes", nargs="*", metavar="chave=valor",
                   help="ex: lan.dhcp.inicio=20 dns.criptografado=true")

    p = sub.add_parser("dhcp", help="aparelhos conectados e IPs fixos")
    p.add_argument("acao", choices=["clientes", "fixar", "soltar"])
    p.add_argument("--mac")
    p.add_argument("--ip")
    p.add_argument("--nome")

    p = sub.add_parser("redir", help="redirecionamento de portas")
    p.add_argument("acao", choices=["add", "rm"])
    p.add_argument("--nome", required=True)
    p.add_argument("--proto", choices=["tcp", "udp"], default="tcp")
    p.add_argument("--porta-externa", type=int)
    p.add_argument("--ip")
    p.add_argument("--porta-interna", type=int)

    p = sub.add_parser("tor", help="navegação da LAN pela rede Tor")
    p.add_argument("acao", choices=["on", "off", "status"])

    p = sub.add_parser("remoto", help="acesso remoto via Tailscale")
    p.add_argument("acao", choices=["on", "off", "status", "login", "logout"])
    p.add_argument("--lan", action="store_true", help="anuncia a LAN do dongle")
    p.add_argument("--saida", action="store_true", help="dongle vira exit node")

    p = sub.add_parser("bluetooth", help="Bluetooth: status, ligar, buscar, parear, conectar…")
    p.add_argument("acao", choices=["status", "ligar", "desligar", "visivel", "oculto", "buscar",
                                    "parear", "responder", "conectar", "desconectar",
                                    "esquecer", "reconciliar"])
    p.add_argument("valor", nargs="?", help="MAC do aparelho, ou a resposta do pareamento")

    p = sub.add_parser("audio", help="placas de som e áudio Bluetooth")
    p.add_argument("acao", nargs="?", default="status",
                   choices=["status", "volume", "mudo", "som", "padrao", "testar", "bluetooth"])
    p.add_argument("valores", nargs="*",
                   help="volume PLACA CONTROLE PCT · mudo PLACA CONTROLE on|off · padrao PLACA · "
                        "testar PLACA [saida|entrada] · bluetooth on|off")

    p = sub.add_parser("usb", help="aparelhos USB plugados e papel da porta")
    p.add_argument("acao", nargs="?", default="status", choices=["status", "host", "device"])

    p = sub.add_parser("servicos", help="serviços do boot (listar, ligar, desligar)")
    p.add_argument("acao", nargs="?", default="listar", choices=["listar", "ligar", "desligar"])
    p.add_argument("nome", nargs="?")

    sub.add_parser("hardware", help="placa, eMMC, rádios, modem e MACs")

    p = sub.add_parser("hora", help="data e hora (status, auto on|off, ajustar)")
    p.add_argument("acao", choices=["status", "auto", "ajustar"])
    p.add_argument("valor", nargs="*", help="auto: on|off · ajustar: AAAA-MM-DD HH:MM")

    p = sub.add_parser("espaco", help="espaço em disco (status, analisar, liberar)")
    p.add_argument("acao", nargs="?", default="status", choices=["status", "analisar", "liberar"])

    p = sub.add_parser("atualizacoes", help="atualizações do sistema")
    p.add_argument("acao", nargs="?", default="status", choices=["status", "verificar", "instalar"])

    sub.add_parser("reiniciar", help="reinicia o dongle")
    sub.add_parser("desligar", help="desliga o dongle (religar: tirar e recolocar)")

    p = sub.add_parser("logs", help="log do sistema (ou de um serviço)")
    p.add_argument("unidade", nargs="?", default="", choices=list(eng.UNITS_LOG))
    p.add_argument("-n", type=int, default=200)

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
    elif args.cmd == "usuario":
        res = eng.renomear_usuario(args.novo)
    elif args.cmd == "config":
        if args.acao == "set":
            if not args.atribuicoes:
                ap.error("config set precisa de chave=valor")
            res = eng.config_set(args.atribuicoes)
        else:
            res = eng.config_show() if args.acao == "show" else eng.config_aplicar()
    elif args.cmd == "dhcp":
        if args.acao == "clientes":
            res = eng.dhcp_clientes()
            if not args.json:
                for c in res["clientes"]:
                    print(f"  {c['ip']:<16} {c['mac']}  {c['nome'] or '-'}"
                          f"{'  (fixo)' if c['fixo'] else ''}")
                return
        elif args.acao == "fixar":
            res = eng.dhcp_fixo_add(args.mac, args.ip, args.nome)
        else:
            res = eng.dhcp_fixo_rm(args.mac)
    elif args.cmd == "redir":
        res = (eng.fw_redir_add(args.nome, args.proto, args.porta_externa, args.ip,
                                args.porta_interna)
               if args.acao == "add" else eng.fw_redir_rm(args.nome))
    elif args.cmd == "tor":
        if args.acao == "status":
            res = eng.tor_status()
            if not args.json:
                print(f"Tor: {'ligado' if res['ativo'] else 'desligado'}"
                      f"{' (rodando, ' + str(res['progresso']) + '%)' if res['rodando'] else ''}"
                      f"{'' if res['instalado'] else ' — não instalado'}")
                return
        else:
            res = eng.tor_set(args.acao == "on")
    elif args.cmd == "remoto":
        if args.acao == "status":
            res = eng.remoto_status()
            if not args.json:
                print(f"Acesso remoto: {'ligado' if res['ativo'] else 'desligado'} "
                      f"({res['estado']}) LAN={res['lan']} saída={res['saida']}")
                for campo in ("nome", "ips", "link_login"):
                    if res[campo]:
                        print(f"  {campo}: {res[campo]}")
                return
        elif args.acao in ("on", "off"):
            res = eng.remoto_set(args.acao == "on", args.lan, args.saida)
        elif args.acao == "login":
            res = eng.remoto_login()
        else:
            res = eng.remoto_logout()
        if res.get("link_login") and not args.json:
            print(f"Login: {res['link_login']}")
    elif args.cmd == "bluetooth":
        a = args.acao
        if a == "status":
            res = bt.estado()
            if res["ok"] and not args.json:
                print(f"Bluetooth {'ligado' if res['ligado'] else 'desligado'} · {res['nome']} "
                      f"· {'visível' if res['visivel'] else 'oculto'}")
                for x in res["aparelhos"]:
                    extra = [x["tipo"]] + (["pareado"] if x["pareado"] else []) + \
                        (["conectado"] if x["conectado"] else []) + \
                        ([f"bateria {x['bateria']}%"] if x["bateria"] is not None else [])
                    print(f"  {x['mac']}  {x['nome']}  ({', '.join(extra)})")
                if res["pareamento"]:
                    print(f"  pareamento: {res['pareamento']}")
                return
        elif a in ("ligar", "desligar"):
            res = bt.ligar(a == "ligar")
        elif a in ("visivel", "oculto"):
            res = bt.visivel(a == "visivel")
        elif a == "buscar":
            res = bt.buscar()
        elif a == "reconciliar":
            res = bt.reconciliar()
        else:
            if not args.valor:
                ap.error(f"bluetooth {a} precisa de um valor (MAC ou resposta)")
            res = {"parear": bt.parear, "responder": bt.responder, "conectar": bt.conectar,
                   "desconectar": bt.desconectar, "esquecer": bt.esquecer}[a](args.valor)
    elif args.cmd == "audio":
        a, v = args.acao, args.valores
        if a == "status":
            res = aud.placas()
            if not args.json:
                for pl in res["placas"]:
                    print(f"{pl['id']}: {pl['nome']}{' (padrão)' if pl['id'] == res['padrao'] else ''}")
                    for c in pl["controles"]:
                        print(f"  {c['nome']} ({c['tipo']}): {c['volume']}%{' mudo' if c['mudo'] else ''}")
                if not res["placas"]:
                    print("Nenhuma placa de som conectada.")
                print(f"Áudio Bluetooth: {'ligado' if aud.bt_ativo() else 'desligado'}")
                return
        elif a == "volume" and len(v) == 3:
            res = aud.ajustar(v[0], v[1], v[2])
        elif a in ("mudo", "som") and len(v) == 2:
            res = aud.ajustar(v[0], v[1], mudo=(a == "mudo"))
        elif a == "padrao" and len(v) <= 1:
            res = eng.audio_placa_padrao(v[0] if v else "")
        elif a == "testar" and v:
            res = (aud.testar_entrada if v[1:] == ["entrada"] else aud.testar_saida)(v[0])
        elif a == "bluetooth" and v in (["on"], ["off"]):
            res = eng.audio_bt_set(v == ["on"])
        else:
            ap.error("argumentos inválidos pra 'audio' (veja --help)")
    elif args.cmd == "usb":
        if args.acao == "status":
            res = sis.usb_dispositivos()
            if not args.json:
                print(f"Papel da porta: {res['papel']}")
                for x in res["aparelhos"]:
                    print(f"  {x['id']}  {x['nome']}  ({x['tipo']})")
                return
        else:
            res = sis.usb_papel(args.acao)
    elif args.cmd == "servicos":
        if args.acao == "listar":
            res = sis.servicos()
            if not args.json:
                for x in res["servicos"]:
                    marca = "essencial" if x["essencial"] else (f"gerenciado: {x['gerenciado']}"
                                                                if x["gerenciado"] else "livre")
                    print(f"  {'●' if x['rodando'] else '○'} {x['nome']:<40} "
                          f"{'boot' if x['habilitado'] else '    '} {x['ram_mb']:5.1f} MB  {marca}")
                return
        else:
            if not args.nome:
                ap.error("servicos ligar|desligar NOME")
            res = sis.servico_set(args.nome, args.acao == "ligar")
    elif args.cmd == "hardware":
        res = sis.hardware()
        if not args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return
    elif args.cmd == "hora":
        if args.acao == "status":
            res = sis.hora_status()
            if not args.json:
                print(f"{res['agora']} · fuso {res['fuso']} · automática "
                      f"{'ligada' if res['automatica'] else 'desligada'}"
                      f"{' (sincronizada)' if res['sincronizada'] else ''}")
                return
        elif args.acao == "auto":
            if args.valor not in (["on"], ["off"]):
                ap.error("use: hora auto on|off")
            res = eng.hora_set(args.valor == ["on"], sis.hora_status()["fuso"])
        else:
            if len(args.valor) != 2:
                ap.error("use: hora ajustar AAAA-MM-DD HH:MM")
            res = sis.hora_manual(*args.valor)
    elif args.cmd == "espaco":
        if args.acao == "status":
            res = sis.espaco_status()
            if not args.json:
                for d in res["discos"]:
                    print(f"{d['nome']}: {d['livre_mb']} MB livres de {d['total_mb']} MB ({d['usado_pct']}% usado)")
                for p in (res["analise"] or {}).get("pastas", []):
                    print(f"  {p['mb']:8.1f} MB  {p['caminho']}")
                return
        else:
            res = sis.espaco_analisar() if args.acao == "analisar" else sis.espaco_liberar()
    elif args.cmd == "atualizacoes":
        if args.acao == "status":
            res = sis.atualizacoes_status()
            if not args.json:
                print(f"etapa: {res.get('etapa')} · pendentes: {res.get('pendentes')}"
                      f"{' · rodando' if res['rodando'] else ''}")
                return
        else:
            res = sis.atualizacoes_iniciar(args.acao == "instalar")
    elif args.cmd in ("reiniciar", "desligar"):
        res = sis.energia("reboot" if args.cmd == "reiniciar" else "poweroff")
    elif args.cmd == "logs":
        res = eng.logs(args.unidade, args.n)
        if res["ok"] and not args.json:
            print(res["texto"])
            return
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
