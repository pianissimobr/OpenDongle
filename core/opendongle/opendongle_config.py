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

# Marcador do SSID ainda não escolhido: vira OpenDongle_<4 hex do id> no
# primeiro carregamento. Ver _ssid_unico.
SSID_A_GERAR = "@id@"
NOME_BASE_SSID = "OpenDongle"
SUFIXO_SSID_HEX = 4
ID_APARELHO = os.environ.get("OPENDONGLE_ID_ARQUIVO", "/etc/opendongle/id")

# O que a imagem OpenStick já traz gravado no hotspot. Não é escolha de
# ninguém — é o estado de fábrica do primeiro boot. Adotá-lo como se fosse
# "nome que o dono escolheu" travava o P-5 inteiro: o painel anunciava
# OpenDongle_<4 hex> enquanto o dongle continuava no 4G-UFI-XX, e o celular
# do cliente achava uma rede que não era a da tela. Só um nome QUE ALGUÉM
# TROCOU é preservado. (Mesma senha: 1234567890 é a de fábrica.)
# "OpenDongle" sem sufixo era o nome fixo que as versões antigas do instalador
# gravavam (--ssid OpenDongle): também é fábrica, não escolha. Visto num dongle
# atualizado em 2026-10-26, que ficou com o nome fixo de antes.
SSID_DE_FABRICA = {"4G-UFI-XX", "OpenDongle"}
SENHA_DE_FABRICA = {"1234567890"}

PADRAO = {
    "versao": 2,
    "sistema": {
        "hostname": "opendongle",
        "fuso": "America/Sao_Paulo",
        "hora_automatica": True,   # acertar o relógio pela internet (NTP)
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
        # o nome da rede precisa ser único por aparelho: dois dongles na
        # mesma casa com "OpenDongle" fariam o celular pular entre os dois.
        # O marcador abaixo é trocado por OpenDongle_<4 hex do id> quando a
        # config ainda não tem um nome escolhido por ninguém (ver _ssid_unico).
        # Assim, quem já trocou o nome não é sobrescrito.
        "hotspot": {"ssid": SSID_A_GERAR, "senha": "opendongle",
                    "canal": 1, "pais": "BR"},
        # a rede da sessão atual (a última em que o dongle entrou)
        "cliente": {"ssid": "", "senha": ""},
        # O hotspot é o modo de RESGATE: sem conexão automática, todo boot
        # sobe nele, mesmo conhecendo redes. Com 'auto', o dongle procura no
        # boot as redes marcadas e só vira hotspot se nenhuma aparecer — então
        # nem assim dá pra perder o dongle de vista.
        "auto": False,
        "auto_todas": True,
        # redes que o dongle já conhece: {"ssid", "senha", "auto"}
        "conhecidas": [],
    },
    # ativo: a internet pelo 4G. Ligada, o dongle conecta sozinho sempre que
    # estiver sem internet (qualquer papel USB); só fica fora se desligarem.
    # no_pc: plugado no computador (papel USB "device") o 4G fica desligado
    # por padrão — no USB de notebook ele esquentou a 78–80° (na tomada, 63–66°)
    "wan": {"ativo": True, "no_pc": False, "apn_extra": {}},
    "dns": {"criptografado": False, "servidores": ["1.1.1.1", "8.8.8.8"]},
    # "wan" aqui é o 4G. A rede em que o dongle entra como cliente Wi-Fi é
    # confiável por padrão: é por ela que o painel e o opendongle_localizar
    # acham o dongle em casa.
    "firewall": {"redirecionamentos": [], "wifi_cliente_confiavel": True,
                 "ssh_pela_wan": False, "painel_pela_wan": False},
    # navegação dos aparelhos da LAN pela rede Tor (proxy transparente)
    "tor": {"ativo": False},
    # Tailscale: acessar o dongle de longe; lan = anuncia a sub-rede da LAN,
    # saida = dongle vira exit node (internet dele usada de longe)
    "remoto": {"ativo": False, "lan": False, "saida": False},
    # placa: id ALSA da placa padrão ("" = automático); bluetooth: PipeWire ligado
    "audio": {"placa": "", "bluetooth": False},
}

MAX_CONHECIDAS = 12   # redes Wi-Fi guardadas (com senha); passou disso, cai a mais antiga

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
        if not isinstance(s["hora_automatica"], bool):
            erros.append("sistema.hora_automatica deve ser true/false.")
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
        # o marcador do SSID é válido enquanto ninguém escolheu um nome: o
        # _ssid_unico troca por OpenDongle_<4 hex> assim que der para ler o id
        if hs["ssid"] != SSID_A_GERAR:
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
        if not (isinstance(wifi["auto"], bool) and isinstance(wifi["auto_todas"], bool)):
            erros.append("wifi.auto e wifi.auto_todas devem ser true/false.")
        if len(wifi["conhecidas"]) > MAX_CONHECIDAS:
            erros.append(f"No máximo {MAX_CONHECIDAS} redes conhecidas.")
        vistos = set()
        for r in wifi["conhecidas"]:
            e = validar_ssid(r.get("ssid", "")) or (r.get("senha") and
                                                    validar_senha_wifi(r["senha"]))
            if e:
                erros.append(f"Rede conhecida: {e}")
            elif r["ssid"] in vistos:
                erros.append(f"Rede conhecida repetida: {r['ssid']}")
            vistos.add(r.get("ssid"))
            if not isinstance(r.get("auto"), bool):
                erros.append("Rede conhecida: 'auto' deve ser true/false.")

        for chave in ("ativo", "no_pc"):
            if not isinstance(cfg["wan"][chave], bool):
                erros.append(f"wan.{chave} deve ser true/false.")
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
        if not re.match(r"^([A-Za-z0-9_]{1,15})?$", str(cfg["audio"]["placa"])):
            erros.append("Identificador de placa de som inválido.")
        for secao, chaves in (("tor", ("ativo",)), ("remoto", ("ativo", "lan", "saida")),
                              ("audio", ("bluetooth",))):
            for chave in chaves:
                if not isinstance(cfg[secao][chave], bool):
                    erros.append(f"{secao}.{chave} deve ser true/false.")
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


def sincronizar_perfil_nm(ssid: str, senha: str) -> bool:
    """Mantém o perfil do hotspot do NetworkManager em dia com o config central.

    DEPOIS DA MIGRAÇÃO quem manda no hotspot é o hostapd, e o NM fica
    masked (ver opendongle_apply._aplicar_rede). Mas o arquivo continua no
    disco, com os valores de fábrica da imagem base, e tem cara de "a
    configuração de rede": ssid= e psk= legíveis, no lugar óbvio de se
    procurar. O resultado é um arquivo que MENTE — mostra um SSID que não
    existe em nenhum outro lugar. Quem for investigar lê ele primeiro e
    chega na resposta errada. Foi o que aconteceu aqui.

    Reescrever, e não apagar: existe migração reversa (o apply faz
    'systemctl unmask' do NM). Apagado, desfazer a migração deixaria o
    hotspot sem perfil nenhum.

    Devolve True se escreveu.
    """
    if not os.path.exists(NM_HOTSPOT):
        return False          # NM nunca esteve aqui: nada a sincronizar
    try:
        with open(NM_HOTSPOT) as f:
            linhas = f.read().splitlines()
    except OSError:
        return False
    novos = {"ssid": ssid, "psk": senha}
    vistos = set()
    mudou = False
    saida = []
    for linha in linhas:
        chave = linha.split("=", 1)[0].strip() if "=" in linha else ""
        if chave in novos:
            if linha != f"{chave}={novos[chave]}":
                mudou = True
            saida.append(f"{chave}={novos[chave]}")
            vistos.add(chave)
        else:
            saida.append(linha)
    faltando = [c for c in novos if c not in vistos]
    if not mudou and not faltando:
        return False          # já estava certo: não toca no arquivo
    try:
        tmp = NM_HOTSPOT + ".tmp"
        with open(tmp, "w") as f:
            f.write("\n".join(saida + [f"{c}={novos[c]}" for c in faltando]) + "\n")
        os.chmod(tmp, 0o600)  # o NM é 0600: a senha do hotspot fica nele
        os.replace(tmp, NM_HOTSPOT)
        return True
    except OSError:
        return False


def migrar_estado_atual():
    """Monta a config a partir do que o dongle já usa, pra ninguém perder
    SSID, senha ou APNs cadastrados ao ganhar a config central. O hostname
    NÃO é migrado: o instalador sempre usa 'opendongle' (opendongle.local),
    e herdar o nome da imagem base faria um 'aplicar' futuro desfazer isso."""
    cfg = copy.deepcopy(PADRAO)
    nm = _ler_ini_nm(NM_HOTSPOT)
    if (nm.get("ssid") and nm["ssid"] not in SSID_DE_FABRICA
            and not validar_ssid(nm["ssid"])):
        cfg["wifi"]["hotspot"]["ssid"] = nm["ssid"]
    if (nm.get("psk") and nm["psk"] not in SENHA_DE_FABRICA
            and not validar_senha_wifi(nm["psk"])):
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


def _ssid_unico(cfg):
    """Se o SSID ainda for o marcador (ou um nome de fábrica), troca por
    OpenDongle_<4 hex do id>. Devolve True se mexeu.

    Só age nesses casos — um nome que o usuário escolheu (no painel, no
    cadastro ou por outra via) nunca é sobrescrito."""
    atual_ssid = cfg.get("wifi", {}).get("hotspot", {}).get("ssid")
    if atual_ssid != SSID_A_GERAR and atual_ssid not in SSID_DE_FABRICA:
        return False
    rotulo = "0000"
    try:
        with open(ID_APARELHO) as f:
            atual = f.read().strip()
        if re.fullmatch(r"[0-9a-f]{16}", atual):
            rotulo = atual[-SUFIXO_SSID_HEX:].upper()
    except OSError:
        pass   # ainda sem id gravado: o instalador roda logo depois e resolve
    cfg["wifi"]["hotspot"]["ssid"] = f"{NOME_BASE_SSID}_{rotulo}"
    return True


def carregar():
    """Config atual. Na primeira vez (arquivo ausente), migra o estado do
    dongle e salva. Arquivo corrompido NÃO é sobrescrito sozinho: levanta
    erro pra quem chamou mostrar e o usuário decidir (restaurar/reset)."""
    if not os.path.exists(CONFIG):
        cfg = migrar_estado_atual()
        _ssid_unico(cfg)
        salvar(cfg)
        return cfg
    with open(CONFIG) as f:
        cfg = _mesclar(PADRAO, json.load(f))
    if _ssid_unico(cfg):
        try:
            salvar(cfg)
        except (OSError, ValueError):
            pass   # sem permissão de escrita: o nome fica em memória até o
                   # instalador rodar de novo
    if _migrar(cfg):
        try:
            salvar(cfg)
        except (OSError, ValueError):
            pass   # sem permissão de escrita: segue com a migração em memória
    return cfg


def _migrar(cfg):
    """Sobe configs de versões anteriores. Devolve True se mexeu."""
    if cfg.get("versao", 1) >= PADRAO["versao"]:
        return False
    # v2: a rede cliente virou uma LISTA de redes conhecidas (com a senha),
    # pra conexão automática poder escolher entre elas
    cl = cfg["wifi"]["cliente"]
    if cl["ssid"] and not any(r["ssid"] == cl["ssid"]
                              for r in cfg["wifi"]["conhecidas"]):
        cfg["wifi"]["conhecidas"].insert(0, {"ssid": cl["ssid"],
                                             "senha": cl["senha"], "auto": True})
    cfg["wifi"].pop("fixar_cliente", None)   # substituído por auto/auto_todas
    cfg["versao"] = PADRAO["versao"]
    return True


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


def atualizar(parcial):
    """Atualiza campos da config (merge por seção) e salva. Devolve a config."""
    cfg = carregar()
    for secao, valores in parcial.items():
        if isinstance(valores, dict) and isinstance(cfg.get(secao), dict):
            cfg[secao].update(valores)
        else:
            cfg[secao] = valores
    salvar(cfg)
    return cfg


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
