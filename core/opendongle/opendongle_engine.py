#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongle_engine.py — MOTOR único de configuração do dongle
=============================================================
Roda NO DONGLE. Concentra TODAS as ações de configuração num só lugar,
para que a CLI (`sudo opendongle`) e o painel web chamem exatamente a
mesma lógica — nunca ficam dessincronizados.

Ações essenciais (todas funcionais):
  - status ............ internet? modo atual? nome do hotspot?
  - set-hotspot ....... troca SSID e senha do hotspot
  - mode-hotspot ...... vira ponto de acesso compartilhando 4G
  - connect-wifi ...... vira cliente de um Wi-Fi existente
  - set-password ...... troca a senha do usuário de administração

Sem dependências externas: só stdlib + nmcli (já presente no Debian
do OpenStick). Retorna dicionários — a casca decide como exibir.
"""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opendongle_apply as aplic
import opendongle_config as conf

HOTSPOT_CON = "hotspot"       # nome da conexão NM do hotspot (minúsculo
                                # na imagem base do OpenStick-Builder)
IFACE_WIFI = "wlan0"
ADMIN_USER = "user"
SSID_PADRAO = "OpenDongle"
SENHA_PADRAO = "opendongle"


def _run(cmd, timeout=40, entrada=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, input=entrada)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", f"comando não encontrado: {cmd[0]}"


# --------------------------------------------------------------- ESTADO DA REDE
# Única fonte de "tem internet?" e "modo do Wi-Fi" (antes copiada no LED e no
# uplink_guard). Com tudo no mesmo processo (opendongled), o laço do uplink
# renova o cache e LED/painel só leem — sem pingar cada um por conta própria.
HOSTS_TESTE = ["1.1.1.1", "8.8.8.8"]
_INTERNET = {"valor": False, "quando": 0.0}


def ip_lan():
    try:
        return conf.carregar()["lan"]["ip"]
    except (ValueError, OSError, KeyError):
        return conf.PADRAO["lan"]["ip"]


def interfaces_uplink():
    """Interfaces candidatas a uplink real: tudo com IPv4 que não seja a
    rede local do dongle (o 4G aparece como wwan0; Wi-Fi cliente, wlan0)."""
    rede = ".".join(ip_lan().split(".")[:3]) + "."
    rc, out, _ = _run(["ip", "-o", "-4", "addr", "show"])
    ifaces = []
    for linha in out.splitlines():
        p = linha.split()
        if len(p) >= 4 and p[1] != "lo" and not p[3].startswith(rede):
            ifaces.append(p[1])
    return ifaces


def tem_internet(max_idade=20):
    """True se sai pra internet por alguma interface que não seja a LAN.
    Reaproveita o último resultado se tiver menos de 'max_idade' segundos."""
    agora = time.monotonic()
    if _INTERNET["quando"] and agora - _INTERNET["quando"] < max_idade:
        return _INTERNET["valor"]
    valor = False
    for iface in interfaces_uplink():
        for host in HOSTS_TESTE:
            rc, _, _ = _run(["ping", "-c", "1", "-W", "2", "-I", iface, host],
                            timeout=6)
            if rc == 0:
                valor = True
                break
        if valor:
            break
    _INTERNET.update(valor=valor, quando=time.monotonic())
    return valor


def _wlan0_associado():
    rc, out, _ = _run(["iw", "dev", IFACE_WIFI, "link"], timeout=5)
    return rc == 0 and out.startswith("Connected")


def _wlan0_tem_ipv4():
    rc, out, _ = _run(["ip", "-o", "-4", "addr", "show", "dev", IFACE_WIFI], timeout=5)
    return rc == 0 and " inet " in f" {out}"


def modo_wifi():
    """'hotspot', 'wifi' (cliente), None (nenhum) ou 'erro' (sem resposta
    do gerenciador de rede)."""
    if aplic.rede_networkd():
        if aplic._ativo(aplic.SVC_AP):
            return "hotspot"
        if aplic._ativo(aplic.SVC_CLIENTE) and _wlan0_associado():
            return "wifi"
        return None
    rc, out, _ = _run(["nmcli", "-t", "-f", "NAME,DEVICE,STATE",
                       "connection", "show", "--active"])
    if rc != 0:
        return "erro"
    ativo = out or ""
    if HOTSPOT_CON.lower() in ativo.lower():
        return "hotspot"
    for linha in ativo.splitlines():
        p = linha.split(":")
        if len(p) >= 2 and p[1] == IFACE_WIFI:
            return "wifi"
    return None


# --------------------------------------------------------------- STATUS
def _modo_atual():
    modo = modo_wifi()
    return modo if modo in ("hotspot", "wifi") else "indefinido"


def _ssid_hotspot():
    if aplic.rede_networkd():
        try:
            return conf.carregar()["wifi"]["hotspot"]["ssid"]
        except (ValueError, OSError):
            return "?"
    rc, out, _ = _run(["nmcli", "-t", "-f", "802-11-wireless.ssid",
                       "connection", "show", HOTSPOT_CON])
    if rc == 0 and ":" in out:
        return out.split(":", 1)[1]
    return "?"


def status():
    modo = _modo_atual()
    return {
        "ok": True,
        "modo": modo,
        "internet": tem_internet(),
        "hotspot_ssid": _ssid_hotspot() if modo != "wifi" else None,
    }


# --------------------------------------------------------------- CONFIG CENTRAL
def _alterar_config(mudanca):
    """Carrega a config, aplica 'mudanca(cfg)' e salva (validando tudo).
    Devolve None se deu certo, ou a mensagem de erro."""
    try:
        cfg = conf.carregar()
        mudanca(cfg)
        conf.salvar(cfg)
    except ValueError as e:
        return str(e)
    except OSError as e:
        return f"Falha ao gravar a config: {e}"
    return None


def config_show():
    try:
        return {"ok": True, "config": conf.carregar()}
    except (ValueError, OSError) as e:
        return {"ok": False, "erro": f"Config ilegível ({e}). Use 'restaurar' "
                "com um backup ou 'reset'."}


def config_aplicar():
    try:
        return aplic.aplicar(conf.carregar())
    except (ValueError, OSError) as e:
        return {"ok": False, "erro": f"Config ilegível: {e}"}


def backup():
    try:
        return {"ok": True, "backup": conf.exportar()}
    except (ValueError, OSError) as e:
        return {"ok": False, "erro": f"Config ilegível: {e}"}


def restaurar(texto):
    try:
        cfg = conf.restaurar(texto or "")
    except ValueError as e:
        return {"ok": False, "erro": str(e)}
    r = aplic.aplicar(cfg)
    if r["ok"]:
        r["aviso"] = "Backup restaurado e aplicado."
    return r


def reset():
    r = aplic.aplicar(conf.reset_fabrica())
    if r["ok"]:
        r["aviso"] = ("Configuração de fábrica aplicada. Wi-Fi: "
                      f"{SSID_PADRAO} / {SENHA_PADRAO}.")
    return r


# --------------------------------------------------------------- HOTSPOT
def set_hotspot(ssid, senha):
    """Troca nome e senha do hotspot. ATENÇÃO: aplica reiniciando a
    conexão — quem estiver conectado cai e precisa reconectar no SSID
    novo. A casca deve avisar o usuário ANTES."""
    ssid = (ssid or "").strip()
    err = conf.validar_ssid(ssid) or conf.validar_senha_wifi(senha or "")
    if err:
        return {"ok": False, "erro": err}
    if aplic.rede_networkd():
        err = _alterar_config(lambda c: c["wifi"]["hotspot"].update(ssid=ssid, senha=senha))
        if err:
            return {"ok": False, "erro": err}
        r = config_aplicar()
        if not r["ok"]:
            return r
        return {"ok": True, "ssid": ssid,
                "aviso": "Reconecte-se ao Wi-Fi com o novo nome e senha."}
    passos = [
        ["nmcli", "connection", "modify", HOTSPOT_CON,
         "802-11-wireless.ssid", ssid],
        ["nmcli", "connection", "modify", HOTSPOT_CON,
         "802-11-wireless-security.key-mgmt", "wpa-psk"],
        ["nmcli", "connection", "modify", HOTSPOT_CON,
         "802-11-wireless-security.psk", senha],
    ]
    for cmd in passos:
        rc, _, err = _run(cmd)
        if rc != 0:
            return {"ok": False, "erro": f"Falha ao aplicar: {err[:120]}"}
    # reinicia a conexão para valer (isto derruba os clientes atuais)
    _run(["nmcli", "connection", "down", HOTSPOT_CON])
    rc, _, err = _run(["nmcli", "connection", "up", HOTSPOT_CON])
    if rc != 0:
        return {"ok": False, "erro": f"Rede não subiu: {err[:120]}"}
    err = _alterar_config(lambda c: c["wifi"]["hotspot"].update(ssid=ssid, senha=senha))
    if err:
        return {"ok": False, "erro": err}
    return {"ok": True, "ssid": ssid,
            "aviso": "Reconecte-se ao Wi-Fi com o novo nome e senha."}


def mode_hotspot():
    """Volta ao modo ponto de acesso (compartilhando o 4G, se houver)."""
    if aplic.rede_networkd():
        err = _alterar_config(lambda c: c["wifi"].update(modo="hotspot"))
        if err:
            return {"ok": False, "erro": err}
        r = config_aplicar()
        return {"ok": True, "modo": "hotspot"} if r["ok"] else r
    _run(["nmcli", "device", "disconnect", IFACE_WIFI], timeout=20)
    rc, _, err = _run(["nmcli", "connection", "up", HOTSPOT_CON])
    if rc != 0:
        return {"ok": False, "erro": f"Não ativou o hotspot: {err[:120]}"}
    err = _alterar_config(lambda c: c["wifi"].update(modo="hotspot"))
    if err:
        return {"ok": False, "erro": err}
    return {"ok": True, "modo": "hotspot"}


def connect_wifi(ssid, senha):
    """Vira CLIENTE de um Wi-Fi existente. O hotspot cai (limitação do
    chip). Acesso pelo cabo USB continua."""
    ssid = (ssid or "").strip()
    senha = senha or ""
    if not ssid:
        return {"ok": False, "erro": "Informe o nome da rede Wi-Fi."}
    err = conf.validar_ssid(ssid) or (senha and conf.validar_senha_wifi(senha))
    if err:
        return {"ok": False, "erro": err}
    if aplic.rede_networkd():
        return _connect_wifi_networkd(ssid, senha)
    cmd = ["nmcli", "device", "wifi", "connect", ssid]
    if senha:
        cmd += ["password", senha]
    cmd += ["ifname", IFACE_WIFI]
    rc, out, err = _run(cmd, timeout=60)
    if rc != 0:
        return {"ok": False, "erro": f"Não conectou: {(err or out)[:140]}"}
    err = _alterar_config(lambda c: (c["wifi"].update(modo="cliente"),
                                     c["wifi"]["cliente"].update(ssid=ssid, senha=senha)))
    if err:
        return {"ok": False, "erro": err}
    return {"ok": True, "modo": "wifi", "ssid": ssid,
            "aviso": "Modo cliente ativo; o hotspot foi desligado."}


ESPERA_CONEXAO = 30   # segundos pra associar e pegar IP por DHCP


def _connect_wifi_networkd(ssid, senha):
    try:
        anterior = conf.carregar()["wifi"]
    except (ValueError, OSError) as e:
        return {"ok": False, "erro": f"Config ilegível: {e}"}
    err = _alterar_config(lambda c: (c["wifi"].update(modo="cliente"),
                                     c["wifi"]["cliente"].update(ssid=ssid, senha=senha)))
    if err:
        return {"ok": False, "erro": err}
    r = config_aplicar()
    if r["ok"]:
        prazo = time.monotonic() + ESPERA_CONEXAO
        while time.monotonic() < prazo:
            if _wlan0_associado() and _wlan0_tem_ipv4():
                return {"ok": True, "modo": "wifi", "ssid": ssid,
                        "aviso": "Modo cliente ativo; o hotspot foi desligado."}
            time.sleep(2)
        motivo = ("não associou (senha errada ou rede fora de alcance?)"
                  if not _wlan0_associado() else "associou mas não recebeu IP")
    else:
        motivo = r["erro"]
    # não deixa o dongle sem Wi-Fi nenhum: volta ao que estava (em geral o
    # hotspot, que é por onde o usuário estava configurando)
    _alterar_config(lambda c: c.update(wifi=anterior))
    config_aplicar()
    return {"ok": False, "erro": f"Não conectou em {ssid}: {motivo}. "
            "O modo anterior foi religado."}


def _listar_wifi_iw():
    """Scan via iw. Em modo AP o wcn36xx costuma recusar o scan normal;
    'ap-force' pede mesmo assim."""
    rc, out, _ = _run(["iw", "dev", IFACE_WIFI, "scan"], timeout=25)
    if rc != 0:
        rc, out, _ = _run(["iw", "dev", IFACE_WIFI, "scan", "ap-force"], timeout=25)
    redes, atual = {}, None
    for linha in (out or "").splitlines():
        s = linha.strip()
        if linha.startswith("BSS "):
            atual = {"ssid": "", "sinal": 0, "seg": "aberta"}
        elif atual is None:
            continue
        elif s.startswith("signal:"):
            dbm = float(s.split()[1])
            atual["sinal"] = max(0, min(100, int(2 * (dbm + 100))))
        elif s.startswith("SSID:"):
            atual["ssid"] = s[5:].strip()
            if atual["ssid"] and atual["sinal"] >= redes.get(atual["ssid"], {}).get("sinal", -1):
                redes[atual["ssid"]] = atual
        elif s.startswith(("RSN:", "WPA:")):
            atual["seg"] = "WPA2" if s.startswith("RSN") else "WPA"
    return list(redes.values())


def listar_wifi():
    """
    Escaneia redes Wi-Fi próximas. PROBLEMA conhecido do chip wcn36xx:
    com o wlan0 ocupado como hotspot (modo AP), o scan retorna pouco ou
    só a própria rede. Então:
      1) forçamos um rescan e lemos o cache do NetworkManager;
      2) filtramos a PRÓPRIA rede do hotspot (não faz sentido "conectar"
         à rede que o próprio dongle emite);
      3) se vier vazio, avisamos que pode ser preciso alternar de modo.
    """
    proprio = _ssid_hotspot()
    if aplic.rede_networkd():
        # o SSID vem inteiro (não dá split em ':'), então não passa pelo
        # parser do nmcli abaixo
        redes = [r for r in _listar_wifi_iw() if r["ssid"] != proprio]
        for r in redes:
            r["sinal"] = str(r["sinal"])
    else:
        # nmcli dev wifi list já dispara rescan; repetimos para dar chance
        # ao rádio de captar algo mesmo em AP.
        _run(["nmcli", "device", "wifi", "rescan"], timeout=20)
        rc, out, _ = _run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY",
                           "device", "wifi", "list"], timeout=30)
        redes, vistos = [], set()
        for linha in (out or "").splitlines():
            p = linha.split(":")
            ssid = p[0] if p else ""
            if not ssid or ssid in vistos:
                continue
            if ssid == proprio:        # não lista a própria rede do dongle
                continue
            vistos.add(ssid)
            redes.append({"ssid": ssid, "sinal": p[1] if len(p) > 1 else "0",
                          "seg": ":".join(p[2:]) or "aberta"})
    redes.sort(key=lambda x: -int(x["sinal"] or 0))
    aviso = ("" if redes else
             "Nenhuma rede além da própria foi vista. O rádio está em "
             "modo hotspot; conectar a um Wi-Fi vai alternar o modo. "
             "Se a lista vier vazia, digite o nome da rede manualmente.")
    return {"ok": True, "redes": redes[:20], "aviso": aviso}


# --------------------------------------------------------------- SAÚDE DO SISTEMA
def _ler_kv_kb(caminho):
    """Lê um arquivo tipo /proc/meminfo (chave: valor kB) num dict de ints."""
    d = {}
    try:
        with open(caminho) as f:
            for linha in f:
                if ":" not in linha:
                    continue
                k, v = linha.split(":", 1)
                try:
                    d[k.strip()] = int(v.strip().split()[0])
                except (ValueError, IndexError):
                    pass
    except OSError:
        pass
    return d


def _temperaturas():
    """Lê todas as zonas térmicas do kernel + o trip point real de
    throttle da CPU (em vez de chutar um limite fixo)."""
    temps, trip_cpu = {}, None
    for base in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        try:
            tipo = open(f"{base}/type").read().strip()
            milic = int(open(f"{base}/temp").read().strip())
        except (OSError, ValueError):
            continue
        temps[tipo] = round(milic / 1000, 1)
        if "cpu" in tipo and trip_cpu is None:
            try:
                trip_cpu = int(open(f"{base}/trip_point_0_temp")
                               .read().strip()) / 1000
            except (OSError, ValueError):
                pass
    return temps, trip_cpu


def saude_sistema():
    """CPU/RAM/disco/temperatura — só leitura de /proc e /sys, zero
    subprocess. Sempre ok=True: arquivo ausente só zera aquele campo,
    não é erro que valha reportar pro usuário."""
    try:
        carga = os.getloadavg()
    except OSError:
        carga = (0.0, 0.0, 0.0)

    mem = _ler_kv_kb("/proc/meminfo")
    mem_total = mem.get("MemTotal", 0)
    # MemAvailable, não MemFree: MemFree sozinho conta só página livre
    # crua e assusta à toa (visto ao vivo: ~29MB "livre" vs ~221MB
    # "disponível" de verdade, no mesmo instante).
    mem_disp = mem.get("MemAvailable", mem.get("MemFree", 0))
    swap_total = mem.get("SwapTotal", 0)
    swap_livre = mem.get("SwapFree", 0)

    try:
        d = shutil.disk_usage("/")
        disco_raiz = {"total_gb": round(d.total / 1e9, 1),
                      "usado_gb": round(d.used / 1e9, 1),
                      "usado_pct": round(d.used / d.total * 100) if d.total else 0}
    except OSError:
        disco_raiz = {"total_gb": 0, "usado_gb": 0, "usado_pct": 0}

    disco_boot = None
    try:
        d = shutil.disk_usage("/boot")
        disco_boot = {"total_mb": round(d.total / 1e6),
                      "usado_pct": round(d.used / d.total * 100) if d.total else 0}
    except OSError:
        pass

    temps, trip_cpu = _temperaturas()
    temp_cpu = max((v for k, v in temps.items() if "cpu" in k), default=None)

    try:
        uptime_s = int(float(open("/proc/uptime").read().split()[0]))
    except (OSError, ValueError, IndexError):
        uptime_s = 0

    return {
        "ok": True,
        "cpu": {"carga_1m": carga[0], "carga_5m": carga[1],
                "carga_15m": carga[2], "nucleos": os.cpu_count() or 1},
        "ram": {"total_kb": mem_total, "disponivel_kb": mem_disp,
                "usada_pct": round((mem_total - mem_disp) / mem_total * 100)
                             if mem_total else 0},
        "swap": {"total_kb": swap_total, "usada_kb": swap_total - swap_livre},
        "disco_raiz": disco_raiz,
        "disco_boot": disco_boot,
        "temperaturas_c": temps,
        "temp_cpu_c": temp_cpu,
        "temp_cpu_trip_c": trip_cpu,
        "uptime_s": uptime_s,
    }


def _unit_do_processo(pid):
    """Nome da unit systemd (ou 'kernel/sem unit') a partir do cgroup v2."""
    try:
        with open(f"/proc/{pid}/cgroup") as f:
            caminho = f.read().strip().rsplit("::", 1)[-1]
    except OSError:
        return None
    partes = [p for p in caminho.split("/") if p]
    for p in reversed(partes):
        if p.endswith((".service", ".scope")):
            # sessões de login viram "session-N.scope": agrupa todas juntas
            return "sessões de login" if p.startswith("session-") else p
    return partes[-1] if partes else "kernel/sem unit"


def recursos():
    """RAM por serviço. Usa PSS (smaps_rollup), que divide as bibliotecas
    compartilhadas entre os processos — somar RSS conta a mesma libc várias
    vezes e infla o total. Cai pro RSS se PSS não for legível (sem root)."""
    por_unit = {}
    usou_pss = True
    for d in glob.glob("/proc/[0-9]*"):
        pid = d.rsplit("/", 1)[-1]
        kb = None
        try:
            with open(f"{d}/smaps_rollup") as f:
                for linha in f:
                    if linha.startswith("Pss:"):
                        kb = int(linha.split()[1])
                        break
            # thread de kernel: smaps_rollup vazio, sem memória de usuário
        except PermissionError:
            usou_pss = False
            kb = _ler_kv_kb(f"{d}/status").get("VmRSS")
        except OSError:
            continue
        if not kb:
            continue   # thread de kernel ou processo que já saiu
        unit = _unit_do_processo(pid)
        if unit is None:
            continue
        por_unit[unit] = por_unit.get(unit, 0) + kb
    mem = _ler_kv_kb("/proc/meminfo")
    return {
        "ok": True,
        "metrica": "PSS" if usou_pss else "RSS (sem root: soma inflada)",
        "ram_total_kb": mem.get("MemTotal", 0),
        "ram_disponivel_kb": mem.get("MemAvailable", 0),
        "servicos": sorted(({"unit": u, "kb": kb} for u, kb in por_unit.items()),
                           key=lambda x: -x["kb"]),
    }


# --------------------------------------------------------------- BLUETOOTH
def bluetooth_status():
    """Só leitura — nunca liga/desliga nada."""
    rc, out, _ = _run(["bluetoothctl", "show"])
    if rc != 0:
        return {"ok": False, "erro": "bluetoothctl indisponível."}
    ligado = "Powered: yes" in out
    visivel = "Discoverable: yes" in out
    nome = next((l.split(":", 1)[1].strip() for l in out.splitlines()
                 if l.strip().startswith("Name:")), "?")

    def _lista(filtro):
        rc, out, _ = _run(["bluetoothctl", "devices", filtro])
        dispositivos = []
        for linha in out.splitlines():
            p = linha.split(" ", 2)
            if len(p) == 3 and p[0] == "Device":
                dispositivos.append({"mac": p[1], "nome": p[2]})
        return dispositivos

    return {"ok": True, "ligado": ligado, "visivel": visivel, "nome": nome,
            "pareados": _lista("Paired"), "conectados": _lista("Connected")}


def bluetooth_power(ligar):
    _run(["rfkill", "unblock" if ligar else "block", "bluetooth"])
    rc, _, err = _run(["hciconfig", "hci0", "up" if ligar else "down"])
    if rc != 0:
        return {"ok": False, "erro": f"Falha: {err[:120]}"}
    return {"ok": True, "aviso": "Ligado." if ligar else
            "Desligado — volta sozinho no próximo boot ou ao reconectar "
            "o modem (usb-role-autosense sempre religa)."}


def bluetooth_scan(segundos=8):
    """Bloqueia de propósito por 'segundos' — mesma filosofia de
    set_hotspot() já bloquear enquanto aplica."""
    _run(["bluetoothctl", "--timeout", str(segundos), "scan", "on"],
         timeout=segundos + 5)
    rc, out, _ = _run(["bluetoothctl", "devices"])
    encontrados = []
    for linha in out.splitlines():
        p = linha.split(" ", 2)
        if len(p) == 3 and p[0] == "Device":
            encontrados.append({"mac": p[1], "nome": p[2]})
    return {"ok": True, "encontrados": encontrados}


def bluetooth_pair(mac):
    """Só cobre pareamento 'just works' (sem confirmar código na tela do
    aparelho) — é a limitação real do bluetoothctl em modo não-interativo."""
    mac = (mac or "").strip().upper()
    if not conf.RE_MAC.match(mac):
        return {"ok": False, "erro": "Endereço MAC inválido."}
    rc, out, err = _run(["bluetoothctl", "--timeout", "15", "pair", mac],
                        timeout=20)
    if rc != 0 or "Failed" in out:
        return {"ok": False, "erro": "Não pareou — o aparelho pode exigir "
                "confirmar um código na tela dele, o que esta página não "
                "faz. Tente pelo SSH (bluetoothctl) nesse caso."}
    _run(["bluetoothctl", "trust", mac])
    return {"ok": True, "aviso": f"Pareado com {mac}."}


def bluetooth_forget(mac):
    mac = (mac or "").strip().upper()
    if not conf.RE_MAC.match(mac):
        return {"ok": False, "erro": "Endereço MAC inválido."}
    rc, _, err = _run(["bluetoothctl", "remove", mac])
    if rc != 0:
        return {"ok": False, "erro": f"Falha ao remover: {err[:120]}"}
    return {"ok": True, "aviso": "Removido."}


# --------------------------------------------------------------- MODEM
QMI_DEV = "/dev/wwan0qmi0"


def _qmi(args, timeout=15):
    return _run(["qmicli", "-d", QMI_DEV] + args, timeout=timeout)


def _campo(saida, rotulo):
    for linha in saida.splitlines():
        if rotulo in linha:
            v = linha.split(":", 1)[-1].strip().strip("'")
            # qmicli devolve 'unknown' literalmente quando não há valor
            # (sem SIM, rádio parado etc.) — trata como ausente
            return None if v.lower() == "unknown" else v
    return None


def modem_status():
    """Só leitura via QMI — nunca mexe no rádio. Trata a ausência de SIM
    (texto real confirmado: "error: no-atr-received") como estado
    normal, não como falha.

    IMPORTANTE: o qmicli falha esporadicamente nesse modem (visto ao
    vivo: 1 em 6 chamadas seguidas voltou vazia, sem SIM nem BT
    envolvidos — é o próprio firmware do modem, não algo que dê pra
    consertar aqui). Por isso 'sim_presente' só vira True/False quando
    a resposta realmente contém 'Card state' — senão fica None (não deu
    pra saber agora), nunca assume presença por causa de uma leitura
    vazia."""
    if not os.path.exists(QMI_DEV):
        return {"ok": True, "presente": False}

    rc, out, _ = _qmi(["--uim-get-card-status"])
    sim_presente = ("no-atr-received" not in out) if (rc == 0 and "Card state" in out) else None

    _, out, _ = _qmi(["--nas-get-signal-strength"])
    rssi = None
    m = re.search(r"Current.*?(-?\d+)\s*dBm", out, re.DOTALL)
    if m:
        rssi = int(m.group(1))

    _, out, _ = _qmi(["--nas-get-serving-system"])
    registrado = "registered" in out.lower() and "not-registered" not in out.lower()
    operadora = _campo(out, "Description") or _campo(out, "Selected network")

    _, out, _ = _qmi(["--dms-get-operating-mode"])
    modo_op = _campo(out, "Mode")

    _, out, _ = _qmi(["--dms-get-ids"])
    imei = _campo(out, "IMEI")

    return {"ok": True, "presente": True, "sim_presente": sim_presente,
            "modo_operacao": modo_op, "registrado": registrado,
            "operadora": operadora, "rssi_dbm": rssi, "imei": imei}


def modem_reconectar():
    """Reaplica o usb-role-autosense.sh inteiro — idempotente (grupos/BT/
    LEDs não têm efeito colateral de reaplicar) e refaz o setup 4G com a
    tabela de APN atual."""
    rc, _, err = _run(["systemctl", "restart", "usb-role-autosense.service"],
                      timeout=30)
    if rc != 0:
        return {"ok": False, "erro": f"Falha ao reiniciar: {err[:120]}"}
    return {"ok": True, "aviso": "Reconectando — pode levar alguns segundos."}


def modem_set_apn(mcc_mnc, apn):
    """Grava na config central; o apply gera o /etc/usb-role-autosense-apn.conf
    (lido via 'source' como root no boot — por isso o whitelist rígido do
    opendongle_config e o 'bash -n' antes de gravar)."""
    mcc_mnc = (mcc_mnc or "").strip()
    apn = (apn or "").strip()
    if not conf.RE_MCCMNC.match(mcc_mnc):
        return {"ok": False, "erro": "MCC-MNC inválido (formato: 724-01)."}
    if not conf.RE_APN.match(apn):
        return {"ok": False, "erro": "APN inválido (letras, números, "
                "ponto, traço ou underline)."}
    err = _alterar_config(lambda c: c["wan"]["apn_extra"].update({mcc_mnc: apn}))
    if err:
        return {"ok": False, "erro": err}
    r = config_aplicar()
    if not r["ok"]:
        return r
    return {"ok": True, "aviso": "Salvo. Clique 'Reconectar 4G' para aplicar agora."}


# --------------------------------------------------------------- SENHA ADMIN
def set_password(nova):
    if len(nova) < 6:
        return {"ok": False, "erro": "Use ao menos 6 caracteres."}
    # chpasswd lê "user:senha" do stdin (rodamos como root)
    rc, _, err = _run(["chpasswd"], entrada=f"{ADMIN_USER}:{nova}\n")
    if rc != 0:
        return {"ok": False, "erro": f"Falha ao trocar senha: {err[:120]}"}
    return {"ok": True, "aviso": "Senha de administração atualizada."}


# --------------------------------------------------------------- dispatch
# Usado pela CLI. A web importa as funções diretamente.
ACOES = {
    "status": lambda a: status(),
    "set-hotspot": lambda a: set_hotspot(a.get("ssid"), a.get("senha")),
    "mode-hotspot": lambda a: mode_hotspot(),
    "connect-wifi": lambda a: connect_wifi(a.get("ssid"), a.get("senha")),
    "list-wifi": lambda a: listar_wifi(),
    "set-password": lambda a: set_password(a.get("senha", "")),
    "config-show": lambda a: config_show(),
    "config-aplicar": lambda a: config_aplicar(),
    "backup": lambda a: backup(),
    "restaurar": lambda a: restaurar(a.get("texto", "")),
    "reset": lambda a: reset(),
    "rede-migrar": lambda a: aplic.migrar_para_networkd(),
    "rede-confirmar": lambda a: aplic.confirmar(),
    "rede-reverter": lambda a: aplic.reverter(),
}


def executar(acao, args):
    fn = ACOES.get(acao)
    if not fn:
        return {"ok": False, "erro": f"ação desconhecida: {acao}"}
    return fn(args or {})


if __name__ == "__main__":
    # teste rápido: python3 opendongle_engine.py status
    acao = sys.argv[1] if len(sys.argv) > 1 else "status"
    print(json.dumps(executar(acao, {}), indent=2, ensure_ascii=False))
