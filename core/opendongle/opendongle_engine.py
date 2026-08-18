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

HOTSPOT_CON = "hotspot"        # nome da conexão NM do hotspot (minúsculo
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


# --------------------------------------------------------------- STATUS
def _tem_internet():
    # tenta resolver+pingar sem depender de DNS externo travar
    rc, _, _ = _run(["ping", "-c", "1", "-W", "3", "1.1.1.1"], timeout=8)
    return rc == 0


def _modo_atual():
    """hotspot se a conexão Hotspot está ativa; senão, se wlan0 é cliente
    conectado, 'wifi'; senão 'indefinido'."""
    rc, out, _ = _run(["nmcli", "-t", "-f", "NAME,DEVICE,STATE",
                       "connection", "show", "--active"])
    ativo = out or ""
    if HOTSPOT_CON.lower() in ativo.lower():
        return "hotspot"
    for linha in ativo.splitlines():
        p = linha.split(":")
        if len(p) >= 2 and p[1] == IFACE_WIFI:
            return "wifi"
    return "indefinido"


def _ssid_hotspot():
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
        "internet": _tem_internet(),
        "hotspot_ssid": _ssid_hotspot() if modo != "wifi" else None,
    }


# --------------------------------------------------------------- HOTSPOT
def _validar_senha_wifi(senha):
    # WPA2 exige 8..63 caracteres
    if not (8 <= len(senha) <= 63):
        return "A senha do Wi-Fi precisa ter de 8 a 63 caracteres."
    return None


def set_hotspot(ssid, senha):
    """Troca nome e senha do hotspot. ATENÇÃO: aplica reiniciando a
    conexão — quem estiver conectado cai e precisa reconectar no SSID
    novo. A casca deve avisar o usuário ANTES."""
    ssid = (ssid or "").strip()
    if not (1 <= len(ssid) <= 32):
        return {"ok": False, "erro": "O nome da rede deve ter 1 a 32 "
                "caracteres."}
    err = _validar_senha_wifi(senha)
    if err:
        return {"ok": False, "erro": err}

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
    return {"ok": True, "ssid": ssid,
            "aviso": "Reconecte-se ao Wi-Fi com o novo nome e senha."}


def mode_hotspot():
    """Volta ao modo ponto de acesso (compartilhando o 4G, se houver)."""
    _run(["nmcli", "device", "disconnect", IFACE_WIFI], timeout=20)
    rc, _, err = _run(["nmcli", "connection", "up", HOTSPOT_CON])
    if rc != 0:
        return {"ok": False, "erro": f"Não ativou o hotspot: {err[:120]}"}
    return {"ok": True, "modo": "hotspot"}


def connect_wifi(ssid, senha):
    """Vira CLIENTE de um Wi-Fi existente. O hotspot cai (limitação do
    chip). Acesso pelo cabo USB continua."""
    ssid = (ssid or "").strip()
    if not ssid:
        return {"ok": False, "erro": "Informe o nome da rede Wi-Fi."}
    cmd = ["nmcli", "device", "wifi", "connect", ssid]
    if senha:
        cmd += ["password", senha]
    cmd += ["ifname", IFACE_WIFI]
    rc, out, err = _run(cmd, timeout=60)
    if rc != 0:
        return {"ok": False, "erro": f"Não conectou: {(err or out)[:140]}"}
    return {"ok": True, "modo": "wifi", "ssid": ssid,
            "aviso": "Modo cliente ativo; o hotspot foi desligado."}


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
    # nmcli dev wifi list já dispara rescan; repetimos para dar chance
    # ao rádio de captar algo mesmo em AP.
    _run(["nmcli", "device", "wifi", "rescan"], timeout=20)
    rc, out, _ = _run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY",
                       "device", "wifi", "list"], timeout=30)
    proprio = _ssid_hotspot()
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


_RE_MAC = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")


def bluetooth_pair(mac):
    """Só cobre pareamento 'just works' (sem confirmar código na tela do
    aparelho) — é a limitação real do bluetoothctl em modo não-interativo."""
    mac = (mac or "").strip().upper()
    if not _RE_MAC.match(mac):
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
    if not _RE_MAC.match(mac):
        return {"ok": False, "erro": "Endereço MAC inválido."}
    rc, _, err = _run(["bluetoothctl", "remove", mac])
    if rc != 0:
        return {"ok": False, "erro": f"Falha ao remover: {err[:120]}"}
    return {"ok": True, "aviso": "Removido."}


# --------------------------------------------------------------- MODEM
QMI_DEV = "/dev/wwan0qmi0"
APN_CONF = "/etc/usb-role-autosense-apn.conf"
_RE_MCCMNC = re.compile(r"^\d{3}-\d{2,3}$")
_RE_APN = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


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
    """Valida contra whitelist rígido: o arquivo é lido via 'source' em
    bash, como root, no boot — nada fora do whitelist é aceito. Só
    ACRESCENTA uma linha (bash 'source' faz o último valor repetido
    ganhar — não precisa reescrever o arquivo todo)."""
    mcc_mnc = (mcc_mnc or "").strip()
    apn = (apn or "").strip()
    if not _RE_MCCMNC.match(mcc_mnc):
        return {"ok": False, "erro": "MCC-MNC inválido (formato: 724-01)."}
    if not _RE_APN.match(apn):
        return {"ok": False, "erro": "APN inválido (letras, números, "
                "ponto, traço ou underline)."}
    try:
        # se o arquivo já existe e NÃO termina em \n, a linha nova gruda
        # na anterior sem separação — se a anterior for comentário, a
        # entrada some dentro do comentário (visto ao vivo: sintaxe bash
        # continua válida, mas o mapeamento nunca é lido de verdade).
        precisa_nova_linha = False
        if os.path.exists(APN_CONF) and os.path.getsize(APN_CONF) > 0:
            with open(APN_CONF, "rb") as f:
                f.seek(-1, os.SEEK_END)
                precisa_nova_linha = f.read(1) != b"\n"
        with open(APN_CONF, "a") as f:
            if precisa_nova_linha:
                f.write("\n")
            f.write(f'APN_MAP["{mcc_mnc}"]="{apn}"\n')
    except OSError as e:
        return {"ok": False, "erro": f"Falha ao gravar: {e}"}
    # só verifica sintaxe (nunca executa) antes de confiar que fica
    # válido pro próximo boot, já que o arquivo roda como root
    rc, _, err = _run(["bash", "-n", APN_CONF])
    if rc != 0:
        return {"ok": False, "erro": f"Config ficou inválida: {err[:120]}"}
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
