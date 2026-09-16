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

import ipaddress
import os
import subprocess
import tempfile

import opendongle_config as conf

DIR_ESTADO = "/etc/opendongle"
DIR_ORIG = "/etc/opendongle/orig"        # arquivos da imagem base que substituímos
DNSMASQ_DIR = "/etc/dnsmasq.d"
DNSMASQ_CONF = "/etc/dnsmasq.d/10-opendongle.conf"
# a imagem OpenStick guarda o DHCP/DNS da br0 aqui; nosso arquivo substitui
DNSMASQ_DA_IMAGEM = ["/etc/dnsmasq.d/dhcp.conf"]
FIREWALL_NFT = "/etc/opendongle/firewall.nft"
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
    if cfg["dns"]["criptografado"]:
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
        "cache-size=" + ("0" if cfg["dns"]["criptografado"] else "150"),
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
{regras_wan}\t\tiifname {wan} drop
\t}}

\tchain forward {{
\t\ttype filter hook forward priority filter; policy accept;
\t\t# MSS clamping: evita páginas travando no 4G (MTU menor que 1500)
\t\toifname {wan} tcp flags syn tcp option maxseg size set rt mtu
\t\tct state established,related accept
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
{redir}\t}}

\tchain postrouting {{
\t\ttype nat hook postrouting priority srcnat;
\t\tip saddr {rede} ip daddr != {rede} masquerade
\t\tip6 saddr {LAN6} ip6 daddr != {LAN6} masquerade
\t}}
}}
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


def _aplicar_dnsproxy(ligar):
    rc, _, _ = _run(["systemctl", "is-enabled", "dnsproxy"])
    if (rc == 0) == ligar:
        return False
    _run(["systemctl", "enable" if ligar else "disable", "--now", "dnsproxy"])
    return True


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
        if _aplicar_hostname(cfg["sistema"]["hostname"]):
            mudou.append("hostname")
        if _aplicar_fuso(cfg["sistema"]["fuso"]):
            mudou.append("fuso")
    except (OSError, RuntimeError) as e:
        return {"ok": False, "mudou": mudou, "erro": str(e)}
    return {"ok": True, "mudou": mudou}
