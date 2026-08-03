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

import json
import re
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
