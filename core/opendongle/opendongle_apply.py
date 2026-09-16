#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongle_apply.py — gera os arquivos nativos a partir da config central
===========================================================================
Equivalente aos init scripts do OpenWrt: config.json -> dnsmasq, nftables,
sysctl, APN, hostname, fuso, dnsproxy. Os geradores (gerar_*) são funções
puras (config -> texto), testáveis no PC. aplicar() valida tudo ANTES de
gravar qualquer coisa, e só grava/recarrega o que mudou.
"""

import hashlib
import ipaddress
import json
import os
import subprocess
import tempfile
import time

import opendongle_config as conf

DIR_ESTADO = "/etc/opendongle"
DIR_ORIG = "/etc/opendongle/orig"        # arquivos da imagem base que substituímos
DNSMASQ_DIR = "/etc/dnsmasq.d"
DNSMASQ_CONF = "/etc/dnsmasq.d/10-opendongle.conf"
# a imagem OpenStick guarda o DHCP/DNS da br0 aqui; nosso arquivo substitui
DNSMASQ_DA_IMAGEM = ["/etc/dnsmasq.d/dhcp.conf"]
FIREWALL_NFT = "/etc/opendongle/firewall.nft"
# rede sem NetworkManager: systemd-networkd + hostapd/wpa_supplicant
FLAG_NETWORKD = "/etc/opendongle/rede-networkd"
NET_BR0_NETDEV = "/etc/systemd/network/10-opendongle-br0.netdev"
NET_BR0 = "/etc/systemd/network/11-opendongle-br0.network"
NET_USB0 = "/etc/systemd/network/12-opendongle-usb0.network"
NET_WLAN0 = "/etc/systemd/network/20-opendongle-wlan0.network"
HOSTAPD_CONF = "/etc/hostapd/wlan0.conf"
WPA_CONF = "/etc/wpa_supplicant/wpa_supplicant-wlan0.conf"
SVC_AP = "hostapd@wlan0.service"
SVC_CLIENTE = "wpa_supplicant@wlan0.service"
# serviços que a rede antiga usava e a nova substitui
SVCS_NM = ["NetworkManager.service", "NetworkManager-wait-online.service",
           "NetworkManager-dispatcher.service", "wpa_supplicant.service",
           "networking.service"]
REVERSAO = "/etc/opendongle/reversao.json"
UNIT_REVERSAO = "opendongle-reversao"
PRAZO_REVERSAO = 180
NFTABLES_CONF = "/etc/nftables.conf"
SYSCTL_CONF = "/etc/sysctl.d/90-opendongle.conf"
HOSTS = "/etc/hosts"

LAN_IF = "br0"
WAN_4G = "wwan0"
# wlan0 só é uplink no modo cliente; no hotspot ele é porta da br0 e o
# tráfego chega como iifname br0 — então regras em wlan0 valem nos dois.
WAN_IFS = (WAN_4G, "wlan0")
LAN6 = "dead:beef::/64"     # ULA que a imagem base já usa (IPv6 fica como está)
LAN6_IP = "dead:beef::1"

TOR_TRANS_PORTA = 9040
TOR_DNS_PORTA = 9053
TORRC = "/etc/tor/torrc"
SVC_TOR = "tor.service"

TS_IF = "tailscale0"
TS_PORTA = 41641
TS_REDE4 = "100.64.0.0/10"
TS_REDE6 = "fd7a:115c:a1e0::/48"
SVC_TS = "tailscaled.service"
TS_DROPIN = "/etc/systemd/system/tailscaled.service.d/opendongle.conf"

CABECALHO = "# GERADO pelo OpenDongle a partir de /etc/opendongle/config.json\n" \
            "# Não edite: use o painel ou 'sudo opendongle config'.\n"


def _run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", f"comando não encontrado: {cmd[0]}"


def _rede_lan(cfg):
    lan = cfg["lan"]
    return ipaddress.ip_interface(f"{lan['ip']}/{lan['prefixo']}").network


def _ip_da_faixa(rede, octeto):
    """Troca o último octeto do endereço de rede (mesma semântica do
    start/limit do OpenWrt pra redes /24; em redes maiores fica no
    primeiro /24 da faixa, que é o que o usuário espera ver)."""
    base = int(rede.network_address) & ~0xFF
    return str(ipaddress.ip_address(base + octeto))


# ------------------------------------------------------------ geradores
def gerar_dnsmasq(cfg):
    rede = _rede_lan(cfg)
    dhcp = cfg["lan"]["dhcp"]
    if cfg["tor"]["ativo"]:
        # com Tor, o DNS da LAN também sai pela rede Tor (sem vazamento)
        servidores = [f"server=127.0.0.1#{TOR_DNS_PORTA}"]
    elif cfg["dns"]["criptografado"]:
        servidores = ["server=127.0.0.1#5353", "server=::1#5353"]
    else:
        servidores = [f"server={s}" for s in cfg["dns"]["servidores"]]
    fixos = [f"dhcp-host={f['mac'].lower()},{f['ip']},{f['nome']}"
             for f in dhcp["fixos"]]
    # O gateway (option:router) NÃO é anunciado aqui: quem decide é o
    # uplink_guard, via /etc/dnsmasq.d/zz-uplink-gateway.conf, conforme o
    # dongle tenha internet ou não.
    linhas = [
        f"interface={LAN_IF}",
        "bind-dynamic",
        "no-resolv",
        *servidores,
        # sem dnsproxy na frente, o cache é do próprio dnsmasq (pouca RAM)
        "cache-size=" + ("0" if cfg["dns"]["criptografado"] and not cfg["tor"]["ativo"]
                         else "150"),
        "no-negcache",
        "domain-needed",
        "bogus-priv",
        "localise-queries",
        "expand-hosts",
        "domain=lan," + str(rede),
        "local=/lan/",
        *[f"server=/{d}/" for d in ("bind", "invalid", "local", "localhost",
                                    "onion", "test")],
        f"dhcp-range=set:{LAN_IF},{_ip_da_faixa(rede, dhcp['inicio'])},"
        f"{_ip_da_faixa(rede, dhcp['fim'])},{rede.netmask},{dhcp['lease']}",
        f"dhcp-range=tag:{LAN_IF},::1,constructor:{LAN_IF},ra-names,{dhcp['lease']}",
        "enable-ra",
        "dhcp-lease-max=100",
        "dhcp-authoritative",
        # WPAD: sem isso Windows pede proxy automático e trava navegação
        'dhcp-option=252,"\\n"',
        "dhcp-option=vendor:MSFT,2,1i",
        "dhcp-name-match=set:wpad-ignore,wpad",
        "dhcp-ignore-names=tag:wpad-ignore",
        *fixos,
    ]
    return CABECALHO + "\n".join(linhas) + "\n"


def gerar_firewall(cfg):
    """Tabelas próprias (inet opendongle*), recriadas a cada aplicação. Nunca
    'flush ruleset': isso apagaria regras de VPN/outros serviços do dongle."""
    rede = _rede_lan(cfg)
    fw = cfg["firewall"]
    wan = "{ " + ", ".join(f'"{i}"' for i in WAN_IFS) + " }"

    regras_wan = ""
    if fw["wifi_cliente_confiavel"]:
        regras_wan += '\t\tiifname "wlan0" accept\n'
    abertas_4g = []
    if fw["ssh_pela_wan"]:
        abertas_4g.append("22")
    if fw["painel_pela_wan"]:
        abertas_4g.append("80")
    if abertas_4g:
        regras_wan += (f'\t\tiifname "{WAN_4G}" tcp dport '
                       f"{{ {', '.join(abertas_4g)} }} accept\n")

    redir = "".join(
        f"\t\tiifname {wan} {r['proto']} dport {r['porta_externa']} "
        f"dnat ip to {r['ip']}:{r['porta_interna']} comment \"{r['nome']}\"\n"
        for r in fw["redirecionamentos"])

    tor_forward = tor_nat = ""
    if cfg["tor"]["ativo"]:
        # antes do "established": conexões abertas antes de ligar o Tor não
        # continuam saindo direto. UDP, ICMP e IPv6 da LAN não passam pelo
        # Tor, então são bloqueados (senão vazariam o IP real)
        tor_forward = (f'\t\tiifname "{LAN_IF}" oifname != {{ "{LAN_IF}", "{TS_IF}" }} '
                       'drop comment "tor: nada sai da LAN sem passar pelo Tor"\n')
        tor_nat = (f'\t\tiifname "{LAN_IF}" ip daddr != {rede} ip protocol tcp '
                   f"dnat ip to {cfg['lan']['ip']}:{TOR_TRANS_PORTA} "
                   'comment "tor: TCP da LAN vai pro TransPort"\n')

    remoto_input = remoto_nat = ""
    if cfg["remoto"]["ativo"]:
        # conexão direta entre aparelhos do Tailscale (sem isso cai no relay)
        remoto_input = f"\t\tiifname {wan} udp dport {TS_PORTA} accept\n"
        if cfg["remoto"]["saida"]:
            remoto_nat = (f"\t\tip saddr {TS_REDE4} oifname {wan} masquerade\n"
                          f"\t\tip6 saddr {TS_REDE6} oifname {wan} masquerade\n")

    return CABECALHO + f"""
table inet opendongle
delete table inet opendongle
table inet opendongle {{
\tchain input {{
\t\ttype filter hook input priority filter; policy accept;
\t\tiifname "lo" accept
\t\tct state established,related accept
\t\tct state invalid drop
\t\tiifname "{LAN_IF}" accept
\t\tmeta l4proto {{ icmp, ipv6-icmp }} accept
\t\t# respostas de DHCP no modo cliente chegam em broadcast (sem conntrack)
\t\tiifname {wan} udp dport {{ 68, 546 }} accept
{remoto_input}{regras_wan}\t\tiifname {wan} drop
\t}}

\tchain forward {{
\t\ttype filter hook forward priority filter; policy accept;
\t\t# MSS clamping: evita páginas travando no 4G (MTU menor que 1500)
\t\toifname {wan} tcp flags syn tcp option maxseg size set rt mtu
{tor_forward}\t\tct state established,related accept
\t\tct state invalid drop
\t\tct status dnat accept
\t\tiifname {wan} drop
\t}}
}}

table inet opendongle_nat
delete table inet opendongle_nat
table inet opendongle_nat {{
\tchain prerouting {{
\t\ttype nat hook prerouting priority dstnat;
\t\t# todo DNS da LAN passa pelo dnsmasq do dongle. dnat em vez de
\t\t# redirect: o kernel msm8916 não tem o módulo nft_redir.
\t\tiifname "{LAN_IF}" meta l4proto {{ tcp, udp }} th dport 53 dnat ip to {cfg['lan']['ip']}
\t\tiifname "{LAN_IF}" meta l4proto {{ tcp, udp }} th dport 53 dnat ip6 to {LAN6_IP}
{tor_nat}{redir}\t}}

\tchain postrouting {{
\t\ttype nat hook postrouting priority srcnat;
\t\tip saddr {rede} ip daddr != {rede} masquerade
\t\tip6 saddr {LAN6} ip6 daddr != {LAN6} masquerade
{remoto_nat}\t}}
}}
"""


def _psk_hex(ssid, senha):
    """PSK WPA2 pré-calculada (o mesmo que wpa_passphrase faz): o arquivo não
    guarda a senha em texto e não há aspas pra escapar."""
    return hashlib.pbkdf2_hmac("sha1", senha.encode(), ssid.encode(), 4096, 32).hex()


def gerar_br0_netdev(cfg):
    return CABECALHO + f"[NetDev]\nName={LAN_IF}\nKind=bridge\n\n[Bridge]\nSTP=no\n"


def gerar_br0_network(cfg):
    lan = cfg["lan"]
    # RA e DHCPv6 continuam com o dnsmasq (enable-ra), como na imagem base
    return CABECALHO + f"""[Match]
Name={LAN_IF}

[Link]
RequiredForOnline=no

[Network]
Address={lan['ip']}/{lan['prefixo']}
Address={LAN6_IP}/64
ConfigureWithoutCarrier=yes
LinkLocalAddressing=ipv6
IPv6AcceptRA=no
IPv6SendRA=no
"""


def gerar_usb0_network(cfg):
    # o msm8916-usb-gadget só põe o usb0 na br0 se ela já existir no boot;
    # aqui o networkd garante isso sem depender da ordem
    return CABECALHO + f"""[Match]
Name=usb0

[Link]
RequiredForOnline=no

[Network]
Bridge={LAN_IF}
# porta de bridge não tem IP próprio; sem isso fica "configuring" pra sempre
LinkLocalAddressing=no
"""


def gerar_wlan0_network(cfg):
    return CABECALHO + """[Match]
Name=wlan0

[Link]
RequiredForOnline=no

[Network]
DHCP=yes
IPv6AcceptRA=yes
"""


def gerar_hostapd(cfg):
    hs = cfg["wifi"]["hotspot"]
    return CABECALHO + f"""interface=wlan0
bridge={LAN_IF}
driver=nl80211
ctrl_interface=/run/hostapd
ssid2={hs['ssid'].encode().hex()}
utf8_ssid=1
country_code={hs['pais']}
ieee80211d=1
hw_mode=g
channel={hs['canal']}
ieee80211n=1
wmm_enabled=1
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_psk={_psk_hex(hs['ssid'], hs['senha'])}
"""


def gerar_wpa_supplicant(cfg):
    cl, pais = cfg["wifi"]["cliente"], cfg["wifi"]["hotspot"]["pais"]
    seguranca = (f"psk={_psk_hex(cl['ssid'], cl['senha'])}" if cl["senha"]
                 else "key_mgmt=NONE")
    return CABECALHO + f"""ctrl_interface=DIR=/run/wpa_supplicant GROUP=netdev
update_config=0
country={pais}

network={{
\tssid={cl['ssid'].encode().hex()}
\tscan_ssid=1
\t{seguranca}
}}
"""


def gerar_torrc(cfg):
    # TransPort só no IP da LAN (nunca no Wi-Fi de casa nem no 4G); DNS e
    # .onion via DNSPort local, que o dnsmasq usa como upstream
    return CABECALHO + f"""SocksPort 0
TransPort {cfg['lan']['ip']}:{TOR_TRANS_PORTA} IsolateClientAddr
DNSPort 127.0.0.1:{TOR_DNS_PORTA}
AutomapHostsOnResolve 1
VirtualAddrNetworkIPv4 10.192.0.0/10
AvoidDiskWrites 1
Log notice syslog
"""


# tor sobe no boot antes da br0 ter IP -> falha no bind do TransPort
TOR_DROPIN = "/etc/systemd/system/tor@default.service.d/opendongle.conf"
TOR_DROPIN_CONTEUDO = CABECALHO + """[Unit]
After=systemd-networkd.service

[Service]
Restart=on-failure
RestartSec=5
"""
TS_DROPIN_CONTEUDO = CABECALHO + """[Service]
# /dev/net/tun só existe depois do módulo carregado (não vem como nó estático)
ExecStartPre=-/sbin/modprobe tun
"""


def gerar_sysctl(cfg):
    # só IPv4: ligar forwarding IPv6 faz o kernel ignorar RA no wlan0 cliente
    # e mudaria o IPv6 que a imagem entrega hoje
    return CABECALHO + "net.ipv4.ip_forward=1\n"


def gerar_apn(cfg):
    linhas = [f'APN_MAP["{k}"]="{v}"'
              for k, v in sorted(cfg["wan"]["apn_extra"].items())]
    return CABECALHO + "\n".join(linhas) + ("\n" if linhas else "")


# ------------------------------------------------------------ aplicação
def _ler(caminho):
    try:
        with open(caminho) as f:
            return f.read()
    except OSError:
        return None


def _gravar(caminho, conteudo, modo=0o644):
    # temporário FORA do diretório de destino: o dnsmasq lê qualquer arquivo
    # largado em /etc/dnsmasq.d (um .tmp de gravação interrompida valeria)
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    os.makedirs(DIR_ESTADO, mode=0o700, exist_ok=True)
    tmp = os.path.join(DIR_ESTADO, ".gravando-" + os.path.basename(caminho))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, modo)
    with os.fdopen(fd, "w") as f:
        f.write(conteudo)
    os.replace(tmp, caminho)


def _aposentar_da_imagem():
    """Tira de /etc/dnsmasq.d os arquivos da imagem base que a config central
    substitui, guardando em /etc/opendongle/orig/. Devolve os movidos."""
    movidos = []
    os.makedirs(DIR_ORIG, mode=0o700, exist_ok=True)
    for caminho in DNSMASQ_DA_IMAGEM:
        if os.path.exists(caminho):
            os.replace(caminho, os.path.join(DIR_ORIG, "dnsmasq.d-" + os.path.basename(caminho)))
            movidos.append(caminho)
    return movidos


def _devolver_da_imagem(movidos):
    for caminho in movidos:
        os.replace(os.path.join(DIR_ORIG, "dnsmasq.d-" + os.path.basename(caminho)), caminho)


def _checar_dnsmasq(conteudo):
    """Testa o conjunto que o dnsmasq vai ler DE VERDADE: /etc/dnsmasq.conf +
    todos os drop-ins atuais (menos os que vamos aposentar) + o nosso. Testar
    o arquivo sozinho não pega opção repetida entre arquivos."""
    with tempfile.TemporaryDirectory() as d:
        for nome in os.listdir(DNSMASQ_DIR) if os.path.isdir(DNSMASQ_DIR) else []:
            origem = os.path.join(DNSMASQ_DIR, nome)
            if (origem in DNSMASQ_DA_IMAGEM or origem == DNSMASQ_CONF
                    or not os.path.isfile(origem) or nome == "README"
                    or nome.endswith((".dpkg-dist", ".dpkg-old", ".dpkg-new"))):
                continue
            with open(origem) as a, open(os.path.join(d, nome), "w") as b:
                b.write(a.read())
        with open(os.path.join(d, os.path.basename(DNSMASQ_CONF)), "w") as f:
            f.write(conteudo)
        rc, out, err = _run(["dnsmasq", "--test", "--conf-file=/etc/dnsmasq.conf",
                             f"--conf-dir={d}"])
    return None if rc == 0 else f"dnsmasq: {(err or out)[:200]}"


def _checar(nome, conteudo, cmd_com_arquivo):
    with tempfile.NamedTemporaryFile("w", suffix="." + nome, delete=False) as t:
        t.write(conteudo)
    try:
        rc, out, err = _run(cmd_com_arquivo(t.name))
        return None if rc == 0 else f"{nome}: {(err or out)[:200]}"
    finally:
        os.unlink(t.name)


def _garantir_include_nftables():
    """/etc/nftables.conf é da imagem (carregado no boot); só garante que
    ele inclui o nosso arquivo, sem reescrever o resto."""
    atual = _ler(NFTABLES_CONF) or "#!/usr/sbin/nft -f\n"
    linha = f'include "{FIREWALL_NFT}"'
    if linha not in atual:
        _gravar(NFTABLES_CONF, atual.rstrip("\n") + "\n" + linha + "\n", 0o755)


def _aplicar_hostname(hostname):
    if (_ler("/etc/hostname") or "").strip() == hostname:
        return False
    _run(["hostnamectl", "set-hostname", hostname])
    hosts = _ler(HOSTS) or ""
    linhas = [l for l in hosts.splitlines() if not l.startswith("127.0.1.1")]
    linhas.append(f"127.0.1.1\t{hostname}")
    _gravar(HOSTS, "\n".join(linhas) + "\n")
    _run(["systemctl", "restart", "avahi-daemon"])
    return True


def _aplicar_fuso(fuso):
    if os.path.realpath("/etc/localtime").endswith("/zoneinfo/" + fuso):
        return False
    rc, _, err = _run(["timedatectl", "set-timezone", fuso])
    if rc != 0:
        raise RuntimeError(f"Fuso não aplicado: {err[:120]}")
    return True


LEDS_DIR = "/sys/class/leds"


def _trigger_atual(led):
    texto = _ler(f"{LEDS_DIR}/{led}/trigger") or ""
    ativo = [t for t in texto.split() if t.startswith("[")]
    return ativo[0].strip("[]") if ativo else None


def _aplicar_leds(cfg):
    """LEDs fora do 'auto' ganham um gatilho do kernel (como no System → LED
    Configuration do OpenWrt). Os 'auto' ficam com o opendongled, que lê a
    config e pula os manuais."""
    mudou = []
    for led, gatilho in cfg["sistema"]["leds"].items():
        base = f"{LEDS_DIR}/{led}"
        if gatilho == "auto" or not os.path.isdir(base):
            continue
        trigger, _, dispositivo = gatilho.partition(":")
        if _trigger_atual(led) == trigger and (
                not dispositivo or (_ler(f"{base}/device_name") or "").strip() == dispositivo):
            continue
        try:
            with open(f"{base}/trigger", "w") as f:
                f.write(trigger)
            if trigger == "netdev":   # arquivos só existem depois do trigger
                for arquivo, valor in (("device_name", dispositivo), ("link", "1"),
                                       ("rx", "1"), ("tx", "1")):
                    with open(f"{base}/{arquivo}", "w") as f:
                        f.write(valor)
        except OSError as e:
            raise RuntimeError(f"LED {led}: gatilho {gatilho} não aceito ({e})")
        mudou.append(f"led {led}={gatilho}")
    return mudou


def _dropin(caminho, conteudo):
    if _gravar_se_mudou(caminho, conteudo):
        _run(["systemctl", "daemon-reload"])
        return True
    return False


def _aplicar_tor(cfg):
    """Liga (ou desliga) o daemon Tor. O firewall/dnsmasq de cada modo vêm dos
    geradores; aqui é só o serviço e o torrc."""
    mudou = []
    if not cfg["tor"]["ativo"]:
        if _ativo("tor@default.service") or \
                _run(["systemctl", "is-enabled", "--quiet", SVC_TOR])[0] == 0:
            _run(["systemctl", "disable", "--now", SVC_TOR, "tor@default.service"],
                 timeout=60)
            mudou.append("parou tor")
        return mudou
    if not os.path.exists("/usr/bin/tor"):
        raise RuntimeError("Tor não está instalado.")
    conf_mudou = _gravar_se_mudou(TORRC, gerar_torrc(cfg))
    conf_mudou = _dropin(TOR_DROPIN, TOR_DROPIN_CONTEUDO) or conf_mudou
    if conf_mudou or not _ativo("tor@default.service"):
        _run(["systemctl", "enable", SVC_TOR])
        rc, _, err = _run(["systemctl", "restart", "tor@default.service"], timeout=60)
        if rc != 0:
            raise RuntimeError(f"Tor não subiu: {err[:160]}")
        mudou.append("reiniciou tor")
    return mudou


TS_ESTADO = "/etc/opendongle/.remoto-aplicado"


def _flags_tailscale(cfg):
    r = cfg["remoto"]
    rotas = str(_rede_lan(cfg)) if r["lan"] else ""
    return ["--accept-dns=false", f"--hostname={cfg['sistema']['hostname']}",
            f"--advertise-routes={rotas}",
            f"--advertise-exit-node={'true' if r['saida'] else 'false'}"]


def _aplicar_remoto(cfg):
    mudou = []
    if not cfg["remoto"]["ativo"]:
        if _ativo(SVC_TS) or _run(["systemctl", "is-enabled", "--quiet", SVC_TS])[0] == 0:
            _run(["systemctl", "stop", "opendongle-tailscale-login.service"])
            _run(["systemctl", "disable", "--now", SVC_TS], timeout=60)
            mudou.append("parou tailscaled")
        return mudou
    if not os.path.exists("/usr/sbin/tailscaled"):
        raise RuntimeError("Tailscale não está instalado.")
    if _dropin(TS_DROPIN, TS_DROPIN_CONTEUDO) or not _ativo(SVC_TS):
        _run(["systemctl", "enable", SVC_TS])
        rc, _, err = _run(["systemctl", "restart", SVC_TS], timeout=60)
        if rc != 0:
            raise RuntimeError(f"tailscaled não subiu: {err[:160]}")
        mudou.append("reiniciou tailscaled")
    flags = _flags_tailscale(cfg)
    if _ler(TS_ESTADO) != json.dumps(flags) or mudou:
        # o daemon demora um instante pra abrir o socket depois do restart
        for _ in range(10):
            rc, _, err = _run(["tailscale", "set"] + flags, timeout=30)
            if rc == 0:
                break
            time.sleep(1)
        if rc != 0:
            raise RuntimeError(f"tailscale set falhou: {err[:160]}")
        _gravar(TS_ESTADO, json.dumps(flags), 0o600)
        mudou.append("tailscale set")
    return mudou


def _aplicar_dnsproxy(ligar):
    rc, _, _ = _run(["systemctl", "is-enabled", "dnsproxy"])
    if (rc == 0) == ligar:
        return False
    _run(["systemctl", "enable" if ligar else "disable", "--now", "dnsproxy"])
    return True


# ------------------------------------------------------------ rede (networkd)
def rede_networkd():
    return os.path.exists(FLAG_NETWORKD)


def _ativo(servico):
    return _run(["systemctl", "is-active", "--quiet", servico])[0] == 0


def _gravar_se_mudou(caminho, conteudo, modo=0o644):
    if _ler(caminho) == conteudo:
        return False
    _gravar(caminho, conteudo, modo)
    return True


def _aplicar_rede(cfg):
    """Gera networkd/hostapd/wpa_supplicant e deixa ativo só o serviço do
    modo escolhido (o wcn36xx não faz AP e cliente ao mesmo tempo)."""
    mudou = []
    for caminho, conteudo in ((NET_BR0_NETDEV, gerar_br0_netdev(cfg)),
                              (NET_BR0, gerar_br0_network(cfg)),
                              (NET_USB0, gerar_usb0_network(cfg))):
        if _gravar_se_mudou(caminho, conteudo):
            mudou.append(caminho)
    ap_mudou = _gravar_se_mudou(HOSTAPD_CONF, gerar_hostapd(cfg), 0o600)
    cliente = cfg["wifi"]["modo"] == "cliente"
    cl_mudou = cliente and _gravar_se_mudou(WPA_CONF, gerar_wpa_supplicant(cfg), 0o600)

    if cliente:
        if _gravar_se_mudou(NET_WLAN0, gerar_wlan0_network(cfg)):
            mudou.append(NET_WLAN0)
    elif os.path.exists(NET_WLAN0):
        os.unlink(NET_WLAN0)
        mudou.append(NET_WLAN0)

    if mudou:
        _run(["networkctl", "reload"])
        for iface in ("br0", "usb0", "wlan0"):
            _run(["networkctl", "reconfigure", iface])

    liga, desliga, conf_mudou = ((SVC_CLIENTE, SVC_AP, cl_mudou) if cliente
                                 else (SVC_AP, SVC_CLIENTE, ap_mudou))
    if _ativo(desliga) or _run(["systemctl", "is-enabled", "--quiet", desliga])[0] == 0:
        _run(["systemctl", "disable", "--now", desliga], timeout=40)
        if not cliente:
            # sem o wpa_supplicant o wlan0 fica com o IP do Wi-Fi antigo
            _run(["ip", "addr", "flush", "dev", "wlan0"])
        mudou.append(f"parou {desliga}")
    if conf_mudou or not _ativo(liga):
        _run(["systemctl", "enable", liga])
        rc, _, err = _run(["systemctl", "restart", liga], timeout=40)
        if rc != 0:
            raise RuntimeError(f"{liga} não subiu: {err[:160]}")
        mudou.append(f"reiniciou {liga}")
    return mudou


def _guardar_reversao(estado):
    _gravar(REVERSAO, json.dumps(estado), 0o600)


def agendar_reversao(estado):
    """Equivalente ao 'apply com rollback' do LuCI: se ninguém confirmar em
    PRAZO_REVERSAO segundos (acesso perdido), o dongle volta sozinho."""
    _guardar_reversao(estado)
    _run(["systemctl", "stop", f"{UNIT_REVERSAO}.timer"])
    _run(["systemctl", "reset-failed", f"{UNIT_REVERSAO}.service"])
    cli = os.path.join(os.path.dirname(os.path.abspath(__file__)), "opendongle_cli.py")
    rc, _, err = _run(["systemd-run", f"--unit={UNIT_REVERSAO}",
                       f"--on-active={PRAZO_REVERSAO}",
                       "/usr/bin/python3", cli, "rede", "reverter"])
    if rc != 0:
        raise RuntimeError(f"Não agendei a reversão automática: {err[:160]}")


def confirmar():
    pendente = os.path.exists(REVERSAO)
    _run(["systemctl", "stop", f"{UNIT_REVERSAO}.timer"])
    if pendente:
        os.unlink(REVERSAO)
    return {"ok": True, "aviso": "Configuração de rede confirmada." if pendente
            else "Não havia mudança de rede aguardando confirmação."}


def _ativar_rede_nm():
    for caminho in (NET_BR0_NETDEV, NET_BR0, NET_USB0, NET_WLAN0, FLAG_NETWORKD):
        if os.path.exists(caminho):
            os.unlink(caminho)
    _run(["systemctl", "disable", "--now", SVC_AP, SVC_CLIENTE], timeout=40)
    _run(["networkctl", "reload"])
    _run(["systemctl", "unmask"] + SVCS_NM)
    _run(["systemctl", "enable"] + SVCS_NM)
    _run(["systemctl", "restart", "wpa_supplicant.service", "NetworkManager.service"],
         timeout=60)
    # sem o .network, o networkd tira os IPs da br0 e o NM reativa a conexão
    # "br0" dele sem endereço (visto ao vivo). Quem punha o IP no boot era o
    # ifupdown2: reiniciá-lo devolve 192.168.100.1 (a rede USB pisca uns
    # segundos; quem chama roda como unit do systemd, não morre junto)
    _run(["systemctl", "restart", "networking.service"], timeout=90)


def reverter():
    try:
        estado = json.loads(_ler(REVERSAO) or "")
    except ValueError:
        return {"ok": False, "erro": "Não há mudança de rede pra reverter."}
    os.unlink(REVERSAO)
    # reversão manual: sem isso o timer agendado dispara depois à toa
    _run(["systemctl", "stop", f"{UNIT_REVERSAO}.timer"])
    if estado.get("tipo") == "nm":
        _ativar_rede_nm()
        return {"ok": True, "aviso": "Rede revertida pro NetworkManager."}
    conf.salvar(estado["config"])
    r = aplicar(estado["config"])
    if r["ok"]:
        r["aviso"] = "Configuração de rede anterior restaurada."
    return r


def migrar_para_networkd():
    """Troca NetworkManager + ifupdown2 por systemd-networkd + hostapd/
    wpa_supplicant, mantendo SSID/senha/modo da config central. Agenda a
    reversão automática ANTES de mexer: se o acesso cair, volta sozinho."""
    if rede_networkd():
        return {"ok": True, "aviso": "A rede já usa systemd-networkd."}
    for binario in ("/usr/sbin/hostapd", "/usr/sbin/wpa_supplicant", "/usr/sbin/iw"):
        if not os.path.exists(binario):
            return {"ok": False, "erro": f"{os.path.basename(binario)} não instalado."}
    cfg = conf.carregar()
    agendar_reversao({"tipo": "nm"})
    # mask sem --now no networking.service: pará-lo derruba a br0 (e o SSH)
    _run(["systemctl", "disable", "--now", "NetworkManager.service",
          "wpa_supplicant.service"], timeout=60)
    _run(["systemctl", "disable", "networking.service"])
    _run(["systemctl", "mask"] + SVCS_NM)
    _gravar(FLAG_NETWORKD, "")
    _run(["systemctl", "enable", "--now", "systemd-networkd.service"])
    try:
        mudou = _aplicar_rede(cfg)
    except RuntimeError as e:
        return {"ok": False, "erro": f"{e} — a reversão roda sozinha em "
                f"{PRAZO_REVERSAO // 60} min, ou use 'opendongle rede reverter'."}
    return {"ok": True, "mudou": mudou,
            "aviso": f"Rede migrada. Confirme em até {PRAZO_REVERSAO // 60} min "
                     "com 'opendongle rede confirmar', senão ela volta sozinha."}


def aplicar(cfg=None):
    """Aplica a config inteira. Retorna {"ok", "mudou": [...]} ou
    {"ok": False, "erro"} sem ter gravado nada se algo não passar na
    validação."""
    cfg = cfg or conf.carregar()
    erros = conf.validar(cfg)
    if erros:
        return {"ok": False, "erro": "; ".join(erros)}
    if not os.path.exists(f"/usr/share/zoneinfo/{cfg['sistema']['fuso']}"):
        return {"ok": False, "erro": "Fuso horário não existe neste sistema."}

    # (arquivo, conteúdo, comando que ativa, serviço que precisa estar no ar)
    arquivos = [
        (DNSMASQ_CONF, gerar_dnsmasq(cfg), ["systemctl", "restart", "dnsmasq"], "dnsmasq"),
        (FIREWALL_NFT, gerar_firewall(cfg), ["nft", "-f", FIREWALL_NFT], None),
        (SYSCTL_CONF, gerar_sysctl(cfg), ["sysctl", "-p", SYSCTL_CONF], None),
        (conf.APN_CONF, gerar_apn(cfg), None, None),   # lido no próximo "Reconectar 4G"
    ]

    for erro in (
        _checar_dnsmasq(arquivos[0][1]),
        _checar("nftables", arquivos[1][1], lambda p: ["nft", "-c", "-f", p]),
        _checar("apn", arquivos[3][1], lambda p: ["bash", "-n", p]),
    ):
        if erro:
            return {"ok": False, "erro": f"Config gerada inválida — nada aplicado. {erro}"}

    mudou = []
    # dnsproxy antes do dnsmasq: se o DNS criptografado for ligado, o
    # dnsmasq já sobe apontando pra um dnsproxy que está no ar
    try:
        # Tor ligando: o daemon precisa estar no ar ANTES do firewall mandar
        # o TCP da LAN pro TransPort e do dnsmasq usar o DNSPort
        if cfg["tor"]["ativo"]:
            mudou += _aplicar_tor(cfg)
        dnsproxy_mudou = _aplicar_dnsproxy(cfg["dns"]["criptografado"])
        if dnsproxy_mudou:
            mudou.append("dnsproxy")
        movidos = _aposentar_da_imagem()
        _garantir_include_nftables()
        for caminho, conteudo, ativar, servico in arquivos:
            anterior = _ler(caminho)
            ativo = servico is None or _run(["systemctl", "is-active", servico])[0] == 0
            if anterior == conteudo and ativo and not (movidos and servico == "dnsmasq"):
                continue
            if anterior != conteudo:
                _gravar(caminho, conteudo)
                mudou.append(caminho)
            if not ativar:
                continue
            rc, _, err = _run(ativar)
            if rc == 0:
                continue
            # não deixa o dongle sem DNS/firewall: volta o que estava e reativa
            if anterior is None:
                os.unlink(caminho)
            else:
                _gravar(caminho, anterior)
            if servico == "dnsmasq":
                _devolver_da_imagem(movidos)
                if dnsproxy_mudou:   # a config antiga do dnsmasq depende dele
                    _aplicar_dnsproxy(not cfg["dns"]["criptografado"])
            _run(ativar)
            return {"ok": False, "mudou": mudou,
                    "erro": f"{' '.join(ativar)} falhou ({err[:160]}); "
                            "a configuração anterior foi restaurada."}
        if rede_networkd():
            mudou += _aplicar_rede(cfg)
        if not cfg["tor"]["ativo"]:   # desligando: só depois do firewall normal
            mudou += _aplicar_tor(cfg)
        mudou += _aplicar_remoto(cfg)
        mudou += _aplicar_leds(cfg)
        if _aplicar_hostname(cfg["sistema"]["hostname"]):
            mudou.append("hostname")
        if _aplicar_fuso(cfg["sistema"]["fuso"]):
            mudou.append("fuso")
    except (OSError, RuntimeError) as e:
        return {"ok": False, "mudou": mudou, "erro": str(e)}
    return {"ok": True, "mudou": mudou}
