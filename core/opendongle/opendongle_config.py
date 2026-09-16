#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongle_config.py — configuração central do dongle (equivalente ao UCI)
============================================================================
Um arquivo só (/etc/opendongle/config.json) guarda tudo que é configurável.
Os arquivos nativos (dnsmasq, nftables, sysctl, APN...) são GERADOS a partir
dele pelo opendongle_apply.py — nunca editados à mão.

Tudo que vem daqui acaba escrito como root em arquivos de config, então a
validação é por whitelist: nada de quebra de linha, aspas ou caractere de
controle chega a um gerador.
"""

import copy
import ipaddress
import json
import os
import re

CONFIG = os.environ.get("OPENDONGLE_CONFIG", "/etc/opendongle/config.json")
APN_CONF = "/etc/usb-role-autosense-apn.conf"
NM_HOTSPOT = "/etc/NetworkManager/system-connections/hotspot.nmconnection"

PADRAO = {
    "versao": 1,
    "sistema": {
        "hostname": "opendongle",
        "fuso": "America/Sao_Paulo",
        "leds": {"red:power": "auto", "green:wlan": "auto", "blue:wan": "auto"},
    },
    "lan": {
        "ip": "192.168.100.1",
        "prefixo": 24,
        # início/fim são o último octeto, como o start/limit do OpenWrt
        "dhcp": {"inicio": 10, "fim": 99, "lease": "12h", "fixos": []},
    },
    "wifi": {
        "modo": "hotspot",
        "hotspot": {"ssid": "OpenDongle", "senha": "opendongle",
                    "canal": 1, "pais": "BR"},
        "cliente": {"ssid": "", "senha": ""},
    },
    "wan": {"apn_extra": {}},
    "dns": {"criptografado": False, "servidores": ["1.1.1.1", "8.8.8.8"]},
    # "wan" aqui é o 4G. A rede em que o dongle entra como cliente Wi-Fi é
    # confiável por padrão: é por ela que o painel e o opendongle_localizar
    # acham o dongle em casa.
    "firewall": {"redirecionamentos": [], "wifi_cliente_confiavel": True,
                 "ssh_pela_wan": False, "painel_pela_wan": False},
}

RE_MAC = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")
RE_MCCMNC = re.compile(r"^\d{3}-\d{2,3}$")
RE_APN = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
RE_HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
RE_FUSO = re.compile(r"^[A-Za-z_]+(/[A-Za-z0-9_+\-]+){0,2}$|^UTC$")
RE_NOME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,31}$")
RE_LEASE = re.compile(r"^\d{1,4}[mh]$")
RE_LED = re.compile(r"^(auto|none|default-on|heartbeat|activity|timer|"
                    r"netdev:(wlan0|wwan0|br0|usb0))$")
RE_APN_LINHA = re.compile(r'^APN_MAP\["(\d{3}-\d{2,3})"\]="([A-Za-z0-9_.\-]{1,64})"')


def validar_senha_wifi(senha):
    # WPA2-PSK: 8..63 caracteres ASCII imprimíveis
    if not (8 <= len(senha) <= 63) or not all(32 <= ord(c) < 127 for c in senha):
        return "A senha do Wi-Fi precisa ter de 8 a 63 caracteres (sem acentos)."
    return None


def validar_ssid(ssid):
    if not (1 <= len(ssid.encode()) <= 32) or any(ord(c) < 32 or c == "\x7f"
                                                   for c in ssid):
        return "O nome da rede deve ter 1 a 32 caracteres."
    return None


def _porta_ok(p):
    return isinstance(p, int) and not isinstance(p, bool) and 1 <= p <= 65535


def validar(cfg):
    """Devolve a lista de erros (vazia = config válida)."""
    erros = []
    try:
        s, lan, wifi = cfg["sistema"], cfg["lan"], cfg["wifi"]
        dhcp, fw, dns = lan["dhcp"], cfg["firewall"], cfg["dns"]

        if not RE_HOSTNAME.match(s["hostname"]):
            erros.append("Hostname inválido (minúsculas, números e traço).")
        if not RE_FUSO.match(s["fuso"]):
            erros.append("Fuso horário inválido (ex: America/Sao_Paulo).")
        for led, gatilho in s["leds"].items():
            if led not in PADRAO["sistema"]["leds"] or not RE_LED.match(gatilho):
                erros.append(f"LED/gatilho inválido: {led}={gatilho}")

        rede = None
        if not (isinstance(lan["prefixo"], int) and 16 <= lan["prefixo"] <= 29):
            erros.append("Prefixo da LAN deve ser de 16 a 29.")
        else:
            try:
                rede = ipaddress.ip_interface(f"{lan['ip']}/{lan['prefixo']}").network
                if ipaddress.ip_address(lan["ip"]) in (rede.network_address,
                                                        rede.broadcast_address):
                    erros.append("IP da LAN não pode ser o endereço de rede nem broadcast.")
                if not rede.is_private:
                    erros.append("A LAN precisa usar uma faixa de IP privada.")
            except ValueError:
                erros.append("IP da LAN inválido.")
                rede = None

        if not (isinstance(dhcp["inicio"], int) and isinstance(dhcp["fim"], int)
                and 2 <= dhcp["inicio"] <= dhcp["fim"] <= 254):
            erros.append("Faixa DHCP inválida (início ≤ fim, entre 2 e 254).")
        if not RE_LEASE.match(dhcp["lease"]):
            erros.append("Tempo de lease inválido (ex: 12h, 30m).")
        macs, ips = set(), set()
        for f in dhcp["fixos"]:
            mac = f.get("mac", "")
            if not RE_MAC.match(mac):
                erros.append(f"MAC inválido: {mac}")
            if not RE_NOME.match(f.get("nome", "")):
                erros.append(f"Nome inválido para {mac}.")
            try:
                ip = ipaddress.ip_address(f.get("ip", ""))
                if rede is not None and (ip not in rede or str(ip) == lan["ip"]):
                    erros.append(f"IP fixo {ip} fora da LAN ou igual ao do dongle.")
            except ValueError:
                erros.append(f"IP fixo inválido para {mac}.")
            if mac in macs or f.get("ip") in ips:
                erros.append(f"IP fixo repetido: {mac} / {f.get('ip')}")
            macs.add(mac)
            ips.add(f.get("ip"))

        if wifi["modo"] not in ("hotspot", "cliente"):
            erros.append("Modo do Wi-Fi deve ser hotspot ou cliente.")
        hs, cl = wifi["hotspot"], wifi["cliente"]
        for e in (validar_ssid(hs["ssid"]), validar_senha_wifi(hs["senha"])):
            if e:
                erros.append(f"Hotspot: {e}")
        if not (isinstance(hs["canal"], int) and 1 <= hs["canal"] <= 13):
            erros.append("Canal do hotspot deve ser de 1 a 13.")
        if not re.match(r"^[A-Z]{2}$", hs["pais"]):
            erros.append("País do Wi-Fi deve ter 2 letras (ex: BR).")
        if cl["ssid"] and validar_ssid(cl["ssid"]):
            erros.append(f"Cliente: {validar_ssid(cl['ssid'])}")
        if cl["senha"] and validar_senha_wifi(cl["senha"]):
            erros.append(f"Cliente: {validar_senha_wifi(cl['senha'])}")
        if wifi["modo"] == "cliente" and not cl["ssid"]:
            erros.append("Modo cliente precisa do nome da rede.")

        for mccmnc, apn in cfg["wan"]["apn_extra"].items():
            if not (RE_MCCMNC.match(mccmnc) and isinstance(apn, str)
                    and RE_APN.match(apn)):
                erros.append(f"APN inválido: {mccmnc}={apn}")

        if not isinstance(dns["criptografado"], bool):
            erros.append("dns.criptografado deve ser true/false.")
        if not dns["servidores"]:
            erros.append("Informe ao menos um servidor DNS.")
        for srv in dns["servidores"]:
            try:
                ipaddress.ip_address(srv)
            except ValueError:
                erros.append(f"Servidor DNS inválido: {srv}")

        for chave in ("wifi_cliente_confiavel", "ssh_pela_wan", "painel_pela_wan"):
            if not isinstance(fw[chave], bool):
                erros.append(f"firewall.{chave} deve ser true/false.")
        externas = set()
        for r in fw["redirecionamentos"]:
            nome = r.get("nome", "")
            if not RE_NOME.match(nome):
                erros.append(f"Nome de redirecionamento inválido: {nome}")
            if r.get("proto") not in ("tcp", "udp"):
                erros.append(f"{nome}: protocolo deve ser tcp ou udp.")
            if not (_porta_ok(r.get("porta_externa")) and _porta_ok(r.get("porta_interna"))):
                erros.append(f"{nome}: portas devem ser de 1 a 65535.")
            try:
                ip = ipaddress.ip_address(r.get("ip", ""))
                if rede is not None and ip not in rede:
                    erros.append(f"{nome}: o IP de destino precisa estar na LAN.")
            except ValueError:
                erros.append(f"{nome}: IP de destino inválido.")
            chave = (r.get("proto"), r.get("porta_externa"))
            if chave in externas:
                erros.append(f"{nome}: porta externa já usada em outro redirecionamento.")
            externas.add(chave)
    except (KeyError, TypeError, AttributeError) as e:
        erros.append(f"Estrutura da config inválida (campo {e}).")
    return erros


def _mesclar(padrao, atual):
    """Completa 'atual' com o que faltar em 'padrao' (config de versão antiga
    ganha os campos novos sem perder os valores já definidos)."""
    if not isinstance(padrao, dict) or not isinstance(atual, dict):
        return copy.deepcopy(atual)
    saida = copy.deepcopy(padrao)
    for k, v in atual.items():
        saida[k] = _mesclar(padrao[k], v) if k in padrao else copy.deepcopy(v)
    return saida


def _ler_ini_nm(caminho):
    """Lê ssid/psk de um keyfile do NetworkManager, sem configparser (as
    chaves do NM podem ter caracteres que ele interpreta)."""
    valores = {}
    try:
        with open(caminho) as f:
            for linha in f:
                if "=" in linha:
                    k, v = linha.rstrip("\n").split("=", 1)
                    valores.setdefault(k.strip(), v)
    except OSError:
        pass
    return valores


def migrar_estado_atual():
    """Monta a config a partir do que o dongle já usa, pra ninguém perder
    SSID, senha ou APNs cadastrados ao ganhar a config central. O hostname
    NÃO é migrado: o instalador sempre usa 'opendongle' (opendongle.local),
    e herdar o nome da imagem base faria um 'aplicar' futuro desfazer isso."""
    cfg = copy.deepcopy(PADRAO)
    nm = _ler_ini_nm(NM_HOTSPOT)
    if nm.get("ssid") and not validar_ssid(nm["ssid"]):
        cfg["wifi"]["hotspot"]["ssid"] = nm["ssid"]
    if nm.get("psk") and not validar_senha_wifi(nm["psk"]):
        cfg["wifi"]["hotspot"]["senha"] = nm["psk"]
    try:
        fuso = open("/etc/timezone").read().strip()
        if RE_FUSO.match(fuso):
            cfg["sistema"]["fuso"] = fuso
    except OSError:
        pass
    try:
        with open(APN_CONF) as f:
            for linha in f:
                m = RE_APN_LINHA.match(linha.strip())
                if m:
                    cfg["wan"]["apn_extra"][m.group(1)] = m.group(2)
    except OSError:
        pass
    return cfg


def carregar():
    """Config atual. Na primeira vez (arquivo ausente), migra o estado do
    dongle e salva. Arquivo corrompido NÃO é sobrescrito sozinho: levanta
    erro pra quem chamou mostrar e o usuário decidir (restaurar/reset)."""
    if not os.path.exists(CONFIG):
        cfg = migrar_estado_atual()
        salvar(cfg)
        return cfg
    with open(CONFIG) as f:
        return _mesclar(PADRAO, json.load(f))


def salvar(cfg):
    erros = validar(cfg)
    if erros:
        raise ValueError("; ".join(erros))
    os.makedirs(os.path.dirname(CONFIG), mode=0o700, exist_ok=True)
    tmp = CONFIG + ".tmp"
    # 0600: guarda senhas do Wi-Fi
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, CONFIG)


def exportar():
    return json.dumps(carregar(), ensure_ascii=False, indent=2)


def restaurar(texto):
    """Valida e salva uma config vinda de backup. Não aplica — quem chama
    decide (o engine aplica logo em seguida)."""
    try:
        cfg = _mesclar(PADRAO, json.loads(texto))
    except (ValueError, TypeError):
        raise ValueError("Arquivo de backup não é um JSON válido.")
    salvar(cfg)
    return cfg


def reset_fabrica():
    cfg = copy.deepcopy(PADRAO)
    salvar(cfg)
    return cfg
