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

import base64
import copy
import glob
import json
import os
import pwd
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
ADMIN_UID = 1000   # o usuário de administração é achado pelo UID: o nome pode mudar
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


ESTADO_RUN = "/run/opendongle/estado.json"


def tem_internet(max_idade=20):
    """True se sai pra internet por alguma interface que não seja a LAN.
    Reaproveita o último resultado se tiver menos de 'max_idade' segundos:
    da memória (mesmo processo) ou de /run (o laço do uplink, no opendongled,
    grava lá; o painel web, que dorme e acorda, só lê)."""
    agora = time.monotonic()
    if _INTERNET["quando"] and agora - _INTERNET["quando"] < max_idade:
        return _INTERNET["valor"]
    if max_idade > 0:
        try:
            with open(ESTADO_RUN) as f:
                estado = json.load(f)
            if time.time() - estado["quando"] < max(max_idade, 30):
                return bool(estado["internet"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
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
    try:
        os.makedirs(os.path.dirname(ESTADO_RUN), exist_ok=True)
        with open(ESTADO_RUN + ".tmp", "w") as f:
            json.dump({"internet": valor, "quando": time.time()}, f)
        os.replace(ESTADO_RUN + ".tmp", ESTADO_RUN)
    except OSError:
        pass   # sem root (teste no PC): segue só com o cache em memória
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


# ------------------------------------------------- ENDEREÇO NA REDE DE CASA
# Em modo cliente o hotspot cai (limitação do chip) e o dongle passa a ter o
# endereço que o roteador emprestou — que ninguém tem como adivinhar. Guardamos
# o último visto POR REDE, em disco: assim, plugando o cabo USB (que reinicia o
# dongle), o painel ainda sabe dizer onde ele estava.
ENDERECOS = "/etc/opendongle/enderecos.json"
ID_APARELHO = "/etc/opendongle/id"
ULTIMA_CONEXAO = "/run/opendongle/ultima-conexao.json"


def id_aparelho():
    """Identidade estável e aleatória deste dongle. Não é segredo: serve pro
    localizador do painel ter certeza de que achou ESTE dongle e não outro da
    mesma rede. (O MAC do Wi-Fi não serve: sem persist, muda a cada boot.)"""
    try:
        with open(ID_APARELHO) as f:
            atual = f.read().strip()
        if re.fullmatch(r"[0-9a-f]{16}", atual):
            return atual
    except OSError:
        pass
    novo = os.urandom(8).hex()
    os.makedirs(os.path.dirname(ID_APARELHO), exist_ok=True)
    with open(ID_APARELHO + ".tmp", "w") as f:
        f.write(novo + "\n")
    os.replace(ID_APARELHO + ".tmp", ID_APARELHO)
    return novo


def enderecos_por_rede():
    """{ssid: último IP do dongle nessa rede} — com o lease fixo, é o palpite
    mais provável de onde ele vai estar ao voltar pra mesma rede."""
    return {ssid: reg["ip"] for ssid, reg in _ler_enderecos().items() if reg.get("ip")}


def ultima_conexao():
    """Resultado da última tentativa de virar cliente de um Wi-Fi. Quem
    estava no hotspot perde a resposta quando o hotspot cai; se deu errado, o
    dongle volta ao hotspot e o painel mostra aqui o que aconteceu."""
    try:
        with open(ULTIMA_CONEXAO) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _registrar_conexao(ssid, ok, detalhe):
    try:
        os.makedirs(os.path.dirname(ULTIMA_CONEXAO), exist_ok=True)
        with open(ULTIMA_CONEXAO + ".tmp", "w") as f:
            json.dump({"ssid": ssid, "ok": ok, "detalhe": detalhe, "quando": time.time()},
                      f, ensure_ascii=False)
        os.replace(ULTIMA_CONEXAO + ".tmp", ULTIMA_CONEXAO)
    except OSError:
        pass
MAX_ENDERECOS = 8


def endereco_wifi():
    """IP que o wlan0 recebeu como cliente: {'ip', 'prefixo'} ou None. No
    modo hotspot o wlan0 é porta da bridge e não tem IP próprio."""
    rc, out, _ = _run(["ip", "-o", "-4", "addr", "show", "dev", IFACE_WIFI], timeout=5)
    if rc != 0:
        return None
    for linha in out.splitlines():
        p = linha.split()
        if len(p) >= 4 and p[2] == "inet" and "/" in p[3]:
            ip, _, prefixo = p[3].partition("/")
            if prefixo.isdigit():
                return {"ip": ip, "prefixo": int(prefixo)}
    return None


def ssid_cliente():
    """Nome da rede em que o dongle entrou como cliente ('' se não entrou)."""
    rc, out, _ = _run(["iw", "dev", IFACE_WIFI, "link"], timeout=5)
    if rc != 0 or not out.startswith("Connected"):
        return ""
    for linha in out.splitlines():
        s = linha.strip()
        if s.startswith("SSID:"):
            return s[5:].strip()
    return ""


def _ler_enderecos():
    try:
        with open(ENDERECOS) as f:
            dados = json.load(f)
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def registrar_endereco():
    """Anota o endereço de agora. Chamado pelo laço do uplink a cada 15 s:
    só grava quando MUDA, porque o disco é eMMC. Devolve o registro ou None."""
    end, ssid = endereco_wifi(), ssid_cliente()
    if not end or not ssid:
        return None
    reg = {"ip": end["ip"], "quando": int(time.time())}
    guardados = _ler_enderecos()
    if guardados.get(ssid, {}).get("ip") == reg["ip"]:
        return reg
    guardados[ssid] = reg
    if len(guardados) > MAX_ENDERECOS:   # fica só com as redes mais recentes
        guardados = dict(sorted(guardados.items(),
                                key=lambda kv: kv[1].get("quando", 0),
                                reverse=True)[:MAX_ENDERECOS])
    try:
        os.makedirs(os.path.dirname(ENDERECOS), mode=0o700, exist_ok=True)
        tmp = ENDERECOS + ".tmp"
        with open(tmp, "w") as f:
            json.dump(guardados, f, ensure_ascii=False)
        os.replace(tmp, ENDERECOS)
    except OSError:
        pass   # sem root (teste no PC): segue sem histórico
    return reg


def endereco_cliente():
    """O que o painel mostra: o endereço de agora (se estiver em modo
    cliente) ou o último visto, sempre com a rede e o horário."""
    end, ssid = endereco_wifi(), ssid_cliente()
    if end and ssid:
        return {"ip": end["ip"], "ssid": ssid, "quando": int(time.time()),
                "agora": True}
    guardados = _ler_enderecos()
    if not guardados:
        return None
    ssid, reg = max(guardados.items(), key=lambda kv: kv[1].get("quando", 0))
    if not reg.get("ip"):
        return None
    return {"ip": reg["ip"], "ssid": ssid, "quando": reg.get("quando", 0),
            "agora": False}


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
        "endereco": endereco_cliente(),
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


def _mudar_e_aplicar(mudanca, aviso="Aplicado."):
    """Muda a config, valida, salva e aplica. Se o IP/prefixo da LAN mudar
    (o acesso atual cai), agenda a reversão automática. Se a aplicação
    falhar, volta a config anterior."""
    try:
        cfg = conf.carregar()
    except (ValueError, OSError) as e:
        return {"ok": False, "erro": f"Config ilegível: {e}"}
    anterior = copy.deepcopy(cfg)
    try:
        mudanca(cfg)
    except (ValueError, KeyError, TypeError) as e:
        if "invalid literal" in str(e) or "int() argument" in str(e):
            return {"ok": False, "erro": "Preencha os campos numéricos só com números."}
        return {"ok": False, "erro": str(e.args[0]) if e.args else str(e)}
    erros = conf.validar(cfg)
    if erros:
        return {"ok": False, "erro": "; ".join(erros)}
    lan_mudou = (cfg["lan"]["ip"], cfg["lan"]["prefixo"]) != \
                (anterior["lan"]["ip"], anterior["lan"]["prefixo"])
    if lan_mudou and not aplic.rede_networkd():
        return {"ok": False, "erro": "Trocar o IP da LAN exige a rede migrada "
                "pro systemd-networkd ('opendongle rede migrar')."}
    conf.salvar(cfg)
    if lan_mudou:
        aplic.agendar_reversao({"tipo": "config", "config": anterior})
    r = aplic.aplicar(cfg)
    if not r["ok"]:
        conf.salvar(anterior)
        aplic.aplicar(anterior)
        if lan_mudou:
            aplic.confirmar()
        r["erro"] += " (configuração anterior restaurada)"
        return r
    r["aviso"] = aviso
    if lan_mudou:
        r["confirmar_em"] = cfg["lan"]["ip"]
        r["aviso"] = (f"IP da LAN agora é {cfg['lan']['ip']}. Reconecte e abra "
                      f"http://{cfg['lan']['ip']}/confirmar em até "
                      f"{aplic.PRAZO_REVERSAO // 60} min, senão volta sozinho.")
    return r


def _valor_config(texto):
    """'true'/'12'/'"x"'/'[..]' viram JSON; o resto é string literal."""
    try:
        return json.loads(texto)
    except ValueError:
        return texto


def config_set(atribuicoes):
    """Equivalente ao 'uci set': ['lan.dhcp.inicio=20', 'dns.criptografado=true']."""
    def mudanca(cfg):
        for item in atribuicoes:
            if "=" not in item:
                raise ValueError(f"Use chave=valor: {item}")
            chave, valor = item.split("=", 1)
            partes = chave.strip().split(".")
            alvo = cfg
            for p in partes[:-1]:
                alvo = alvo[p]
            if partes[-1] not in alvo:
                raise KeyError(f"Chave inexistente: {chave}")
            alvo[partes[-1]] = _valor_config(valor)
    return _mudar_e_aplicar(mudanca)


# --------------------------------------------------------------- LAN / DHCP
LEASES = "/var/lib/misc/dnsmasq.leases"


def dhcp_clientes():
    """Dispositivos com IP emprestado pelo dnsmasq agora (formato do arquivo:
    expira mac ip nome client-id)."""
    fixos = {}
    try:
        fixos = {f["mac"]: f for f in conf.carregar()["lan"]["dhcp"]["fixos"]}
    except (ValueError, OSError):
        pass
    clientes = []
    try:
        with open(LEASES) as f:
            for linha in f:
                p = linha.split()
                if len(p) >= 4 and ":" in p[1] and "." in p[2]:
                    mac = p[1].upper()
                    clientes.append({"mac": mac, "ip": p[2],
                                     "nome": "" if p[3] == "*" else p[3],
                                     "expira": int(p[0]), "fixo": mac in fixos})
    except (OSError, ValueError):
        pass
    return {"ok": True, "clientes": sorted(clientes, key=lambda c: c["ip"])}


def lan_set(ip, prefixo, inicio, fim, lease):
    def mudanca(cfg):
        cfg["lan"].update(ip=(ip or "").strip(), prefixo=int(prefixo))
        cfg["lan"]["dhcp"].update(inicio=int(inicio), fim=int(fim),
                                  lease=(lease or "").strip())
    return _mudar_e_aplicar(mudanca, "LAN e DHCP aplicados.")


def dhcp_fixo_add(mac, ip, nome):
    mac = (mac or "").strip().upper()

    def mudanca(cfg):
        fixos = [f for f in cfg["lan"]["dhcp"]["fixos"] if f["mac"] != mac]
        fixos.append({"mac": mac, "ip": (ip or "").strip(), "nome": (nome or "").strip()})
        cfg["lan"]["dhcp"]["fixos"] = fixos
    return _mudar_e_aplicar(mudanca, f"IP fixo salvo. O aparelho recebe o IP "
                            "novo quando renovar a conexão.")


def dhcp_fixo_rm(mac):
    mac = (mac or "").strip().upper()
    return _mudar_e_aplicar(
        lambda cfg: cfg["lan"]["dhcp"].update(
            fixos=[f for f in cfg["lan"]["dhcp"]["fixos"] if f["mac"] != mac]),
        "IP fixo removido.")


# --------------------------------------------------------------- FIREWALL
def fw_redir_add(nome, proto, porta_externa, ip, porta_interna):
    nome = (nome or "").strip()

    def mudanca(cfg):
        redir = [r for r in cfg["firewall"]["redirecionamentos"] if r["nome"] != nome]
        redir.append({"nome": nome, "proto": (proto or "").strip(),
                      "porta_externa": int(porta_externa), "ip": (ip or "").strip(),
                      "porta_interna": int(porta_interna)})
        cfg["firewall"]["redirecionamentos"] = redir
    return _mudar_e_aplicar(mudanca, f"Redirecionamento '{nome}' aplicado.")


def fw_redir_rm(nome):
    return _mudar_e_aplicar(
        lambda cfg: cfg["firewall"].update(redirecionamentos=[
            r for r in cfg["firewall"]["redirecionamentos"] if r["nome"] != nome]),
        "Redirecionamento removido.")


def fw_set(wifi_cliente_confiavel, ssh_pela_wan, painel_pela_wan):
    return _mudar_e_aplicar(
        lambda cfg: cfg["firewall"].update(
            wifi_cliente_confiavel=bool(wifi_cliente_confiavel),
            ssh_pela_wan=bool(ssh_pela_wan), painel_pela_wan=bool(painel_pela_wan)),
        "Regras de acesso aplicadas.")


# --------------------------------------------------------------- SISTEMA
UNITS_LOG = {"": None, "opendongle": "opendongle.service",
             "painel": "opendongle-web.service",
             "dnsmasq": "dnsmasq.service", "hostapd": "hostapd@wlan0.service",
             "wifi-cliente": "wpa_supplicant@wlan0.service",
             "rede": "systemd-networkd.service",
             "usb-4g": "usb-role-autosense.service"}


def sistema_set(hostname):
    return _mudar_e_aplicar(
        lambda cfg: cfg["sistema"].update(hostname=(hostname or "").strip()),
        "Nome do dongle aplicado.")


def hora_set(automatica, fuso):
    return _mudar_e_aplicar(
        lambda cfg: cfg["sistema"].update(hora_automatica=bool(automatica),
                                          fuso=(fuso or "").strip()),
        "Data e hora aplicadas.")


def led_set(led, gatilho):
    def mudanca(cfg):
        if led not in cfg["sistema"]["leds"]:
            raise ValueError(f"LED desconhecido: {led}")
        cfg["sistema"]["leds"][led] = gatilho
    return _mudar_e_aplicar(mudanca, "LED aplicado.")


def logs(unidade="", linhas=200):
    if unidade not in UNITS_LOG:
        return {"ok": False, "erro": "Serviço de log desconhecido."}
    cmd = ["journalctl", "-b", "--no-pager", "-o", "short-iso",
           "-n", str(max(1, min(int(linhas), 1000)))]
    if UNITS_LOG[unidade]:
        cmd += ["-u", UNITS_LOG[unidade]]
    rc, out, err = _run(cmd, timeout=20)
    if rc != 0:
        return {"ok": False, "erro": err[:200]}
    return {"ok": True, "texto": out}


# --------------------------------------------------------------- TOR E ACESSO REMOTO
# Nenhum dos dois vem na instalação base (RAM): o pacote é baixado na primeira
# vez que o usuário liga, e desligar para o daemon.
def _apt_instalar(pacotes):
    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")

    def rodar(cmd, timeout):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
            return r.returncode, (r.stderr or r.stdout).strip()
        except subprocess.TimeoutExpired:
            return 124, "tempo esgotado"
    rc, err = rodar(["apt-get", "update"], 300)
    if rc != 0:
        return f"Sem acesso aos repositórios (o dongle precisa de internet): {err[-160:]}"
    rc, err = rodar(["apt-get", "install", "-y", "--no-install-recommends"] + pacotes, 600)
    rodar(["apt-get", "clean"], 60)
    return None if rc == 0 else f"Instalação falhou: {err[-160:]}"


def tor_status():
    try:
        ativo = conf.carregar()["tor"]["ativo"]
    except (ValueError, OSError):
        ativo = False
    rodando = aplic._ativo("tor@default.service")
    progresso, detalhe = 0, ""
    if rodando:
        _, out, _ = _run(["journalctl", "-u", "tor@default", "-b", "-o", "cat",
                          "--no-pager", "-g", "Bootstrapped"], timeout=15)
        ultima = out.splitlines()[-1] if out else ""
        m = re.search(r"Bootstrapped (\d+)%[^:]*: (.*)", ultima)
        if m:
            progresso, detalhe = int(m.group(1)), m.group(2)
    return {"ok": True, "instalado": os.path.exists("/usr/bin/tor"), "ativo": ativo,
            "rodando": rodando, "progresso": progresso, "detalhe": detalhe}


def tor_set(ligar):
    if ligar and not os.path.exists("/usr/bin/tor"):
        err = _apt_instalar(["tor"])
        if err:
            return {"ok": False, "erro": err}
    r = _mudar_e_aplicar(lambda cfg: cfg["tor"].update(ativo=bool(ligar)),
                         "Navegação via Tor ligada: a conexão com a rede Tor leva "
                         "alguns segundos." if ligar else "Navegação via Tor desligada.")
    return r


def _tailscale_json():
    rc, out, _ = _run(["tailscale", "status", "--json"], timeout=15)
    try:
        return json.loads(out) if out else {}
    except ValueError:
        return {}


def remoto_status():
    try:
        r = conf.carregar()["remoto"]
    except (ValueError, OSError):
        r = dict(conf.PADRAO["remoto"])
    instalado = os.path.exists("/usr/sbin/tailscaled")
    st = _tailscale_json() if instalado and aplic._ativo(aplic.SVC_TS) else {}
    eu = st.get("Self") or {}
    return {"ok": True, "instalado": instalado, "ativo": r["ativo"], "lan": r["lan"],
            "saida": r["saida"], "estado": st.get("BackendState", "Stopped"),
            "link_login": st.get("AuthURL") or "",
            "ips": eu.get("TailscaleIPs") or [],
            "nome": (eu.get("DNSName") or "").rstrip(".")}


def _instalar_tailscale():
    codinome = "trixie"
    try:
        for linha in open("/etc/os-release"):
            if linha.startswith("VERSION_CODENAME="):
                codinome = linha.split("=", 1)[1].strip().strip('"') or codinome
    except OSError:
        pass
    base = f"https://pkgs.tailscale.com/stable/debian/{codinome}"
    for url, destino in ((f"{base}.noarmor.gpg",
                          "/usr/share/keyrings/tailscale-archive-keyring.gpg"),
                         (f"{base}.tailscale-keyring.list",
                          "/etc/apt/sources.list.d/tailscale.list")):
        rc, _, err = _run(["curl", "-fsSL", "--max-time", "60", "-o", destino, url], timeout=90)
        if rc != 0:
            return f"Não baixei o repositório do Tailscale (precisa de internet): {err[:120]}"
    return _apt_instalar(["tailscale"])


def remoto_login(espera=30):
    """Pede um link de login ao Tailscale (roda o 'tailscale up' em segundo
    plano: ele fica esperando o login e não pode travar o painel)."""
    if not aplic._ativo(aplic.SVC_TS):
        return {"ok": False, "erro": "Ligue o acesso remoto primeiro."}
    st = remoto_status()
    if st["estado"] == "Running":
        return {"ok": True, "aviso": "Já está conectado."}
    try:
        cfg = conf.carregar()
    except (ValueError, OSError) as e:
        return {"ok": False, "erro": f"Config ilegível: {e}"}
    # um pedido de login já em andamento é reaproveitado: reiniciar o
    # 'tailscale up' descartaria o registro que o servidor ainda vai responder
    if not aplic._ativo("opendongle-tailscale-login.service"):
        _run(["systemd-run", "--unit=opendongle-tailscale-login", "--collect",
              "tailscale", "up", "--reset"] + aplic._flags_tailscale(cfg))
    prazo = time.monotonic() + espera
    while time.monotonic() < prazo:
        st = remoto_status()
        if st["link_login"] or st["estado"] == "Running":
            break
        time.sleep(1)
    if st["estado"] == "Running":
        return {"ok": True, "aviso": "Conectado ao Tailscale."}
    if st["link_login"]:
        return {"ok": True, "link_login": st["link_login"],
                "aviso": "Abra o link pra entrar na sua conta do Tailscale."}
    # visto ao vivo: o primeiro registro no servidor do Tailscale pode levar
    # mais de um minuto; o link aparece no status assim que chegar
    return {"ok": True, "aviso": "Pedindo o link de login ao Tailscale (a primeira "
            "vez pode levar 1 a 2 minutos). Atualize em instantes."}


def remoto_set(ligar, lan=False, saida=False):
    if ligar and not os.path.exists("/usr/sbin/tailscaled"):
        err = _instalar_tailscale()
        if err:
            return {"ok": False, "erro": err}
    r = _mudar_e_aplicar(
        lambda cfg: cfg["remoto"].update(ativo=bool(ligar), lan=bool(lan), saida=bool(saida)),
        "Acesso remoto ligado." if ligar else "Acesso remoto desligado.")
    if r["ok"] and ligar and remoto_status()["estado"] != "Running":
        login = remoto_login()
        r.update({k: v for k, v in login.items() if k in ("link_login", "aviso")})
    if r["ok"] and ligar and (lan or saida):
        r["aviso"] += (" Rotas da LAN e saída pela internet precisam ser aprovadas "
                       "no painel de admin do Tailscale.")
    return r


def audio_bt_set(ligar):
    import opendongle_audio as audio
    if ligar and not audio.bt_instalado():
        err = _apt_instalar(audio.PACOTES_BT)
        if err:
            return {"ok": False, "erro": err}
    return _mudar_e_aplicar(lambda cfg: cfg["audio"].update(bluetooth=bool(ligar)),
                            "Áudio Bluetooth ligado." if ligar else "Áudio Bluetooth desligado.")


def audio_placa_padrao(placa_id):
    import opendongle_audio as audio
    placa_id = (placa_id or "").strip()
    if placa_id and not audio._placa_por_id(placa_id):
        return {"ok": False, "erro": "Placa de som não encontrada."}
    return _mudar_e_aplicar(lambda cfg: cfg["audio"].update(placa=placa_id),
                            "Placa padrão definida." if placa_id else "Placa padrão: automática.")


def remoto_logout():
    rc, _, err = _run(["tailscale", "logout"], timeout=30)
    if rc != 0:
        return {"ok": False, "erro": f"Falha ao sair: {err[:120]}"}
    return {"ok": True, "aviso": "Saiu da conta do Tailscale."}


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
    if not senha:
        # rede já conhecida: usa a senha guardada. Sem isto, reconectar sem
        # digitar gravava senha vazia por cima da salva.
        try:
            senha = next((r["senha"] for r in conf.carregar()["wifi"]["conhecidas"]
                          if r["ssid"] == ssid), "")
        except (ValueError, OSError, KeyError):
            pass
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
    err = _alterar_config(lambda c: _entrar_na_rede(c, ssid, senha))
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
    err = _alterar_config(lambda c: _entrar_na_rede(c, ssid, senha))
    if err:
        return {"ok": False, "erro": err}
    r = config_aplicar()
    if r["ok"]:
        prazo = time.monotonic() + ESPERA_CONEXAO
        while time.monotonic() < prazo:
            if _wlan0_associado() and _wlan0_tem_ipv4():
                # o endereço emprestado pelo roteador é a única forma de voltar
                # ao painel nessa rede: mostra na hora e guarda pra depois
                ip = (registrar_endereco() or {}).get("ip", "")
                partes = [f"O painel agora atende em http://{ip} nesta rede — anote."
                          if ip else "Modo cliente ativo."]
                partes.append("O hotspot foi desligado.")
                if not aplic.redes_automaticas(conf.carregar()):
                    partes.append("Ao reiniciar, o dongle volta a ser hotspot.")
                _registrar_conexao(ssid, True, ip)
                return {"ok": True, "modo": "wifi", "ssid": ssid, "ip": ip,
                        "aviso": " ".join(partes)}
            time.sleep(2)
        motivo = ("não associou (senha errada ou rede fora de alcance?)"
                  if not _wlan0_associado() else "associou mas não recebeu IP")
    else:
        motivo = r["erro"]
    # não deixa o dongle sem Wi-Fi nenhum: volta ao que estava (em geral o
    # hotspot, que é por onde o usuário estava configurando)
    _alterar_config(lambda c: c.update(wifi=anterior))
    config_aplicar()
    _registrar_conexao(ssid, False, motivo)
    return {"ok": False, "erro": f"Não conectou em {ssid}: {motivo}. "
            "O modo anterior foi religado."}


def reconectar_wifi():
    """Volta pra última rede salva sem pedir a senha de novo. É o caminho
    normal depois de um reinício, já que o boot cai no hotspot de propósito."""
    try:
        cl = conf.carregar()["wifi"]["cliente"]
    except (ValueError, OSError) as e:
        return {"ok": False, "erro": f"Config ilegível: {e}"}
    if not cl["ssid"]:
        return {"ok": False, "erro": "Nenhuma rede Wi-Fi salva ainda."}
    return connect_wifi(cl["ssid"], cl["senha"])


def _entrar_na_rede(cfg, ssid, senha):
    """Marca a rede como a da sessão e guarda entre as conhecidas (a senha
    junto, pra reconectar sem digitar de novo)."""
    cfg["wifi"].update(modo="cliente")
    cfg["wifi"]["cliente"].update(ssid=ssid, senha=senha)
    conhecidas = cfg["wifi"]["conhecidas"]
    for r in conhecidas:
        if r["ssid"] == ssid:
            r["senha"] = senha
            return
    # rede nova entra marcada: se a conexão automática estiver ligada, ela já
    # conta — e desmarcar é um toque na lista
    conhecidas.insert(0, {"ssid": ssid, "senha": senha, "auto": True})
    del conhecidas[conf.MAX_CONHECIDAS:]


def redes_conhecidas():
    """Estado da conexão automática e as redes que o dongle já conhece."""
    try:
        w = conf.carregar()["wifi"]
    except (ValueError, OSError) as e:
        return {"ok": False, "erro": f"Config ilegível: {e}"}
    atual = ssid_cliente()
    return {"ok": True, "auto": w["auto"], "auto_todas": w["auto_todas"],
            "atual": atual, "salva": w["cliente"]["ssid"],
            "redes": [{"ssid": r["ssid"], "auto": r["auto"],
                       "conectada": r["ssid"] == atual} for r in w["conhecidas"]]}


def esquecer_rede(ssid):
    """Tira a rede da lista (a senha some junto). Não derruba a conexão de
    agora: isso é decisão de quem está usando."""
    ssid = (ssid or "").strip()
    achou = [False]

    def mudar(c):
        antes = len(c["wifi"]["conhecidas"])
        c["wifi"]["conhecidas"] = [r for r in c["wifi"]["conhecidas"]
                                   if r["ssid"] != ssid]
        achou[0] = len(c["wifi"]["conhecidas"]) < antes

    err = _alterar_config(mudar)
    if err:
        return {"ok": False, "erro": err}
    if not achou[0]:
        return {"ok": False, "erro": "Essa rede não estava na lista."}
    r = config_aplicar()
    if r["ok"]:
        r["aviso"] = f"A rede {ssid} foi esquecida."
    return r


def wifi_auto(ativo, todas=None, marcadas=None):
    """Conexão automática: liga/desliga e escolhe quais redes entram. Sem
    nenhuma rede marcada, o boot cai no hotspot — que é o modo de resgate."""
    ativo, todas = bool(ativo), bool(todas)
    marcadas = set(marcadas or [])

    def mudar(c):
        c["wifi"].update(auto=ativo, auto_todas=todas)
        for r in c["wifi"]["conhecidas"]:
            r["auto"] = r["ssid"] in marcadas

    err = _alterar_config(mudar)
    if err:
        return {"ok": False, "erro": err}
    r = config_aplicar()
    if not r["ok"]:
        return r
    try:
        quantas = len(aplic.redes_automaticas(conf.carregar()))
    except (ValueError, OSError):
        quantas = 0
    if not ativo:
        r["aviso"] = "Conexão automática desligada: ao ligar, o dongle vira hotspot."
    elif quantas:
        r["aviso"] = (f"Ao ligar, o dongle vai procurar {quantas} rede(s); "
                      "sem nenhuma por perto, vira hotspot.")
    else:
        r["aviso"] = ("Conexão automática ligada, mas nenhuma rede marcada: "
                      "por enquanto o dongle continua virando hotspot ao ligar.")
    return r


ESPERA_AUTO = 60                                 # s pra associar depois de ligar
FLAG_AUTO = "/run/opendongle/auto-decidido"       # tmpfs: zera a cada boot


def _uptime():
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return 1e9


def vigiar_auto_boot():
    """Plano B da conexão automática: se nenhuma rede marcada apareceu até
    ESPERA_AUTO segundos depois de ligar, vira hotspot. Sem isso, um Wi-Fi
    fora do ar deixaria o dongle inalcançável. Decide uma vez por boot."""
    if os.path.exists(FLAG_AUTO):
        return None
    try:
        w = conf.carregar()["wifi"]
    except (ValueError, OSError):
        return None
    decidiu = None
    if w["modo"] != "cliente" or not w["auto"]:
        decidiu = "sem conexão automática"
    elif _wlan0_associado():
        decidiu = "associou"
    elif _uptime() >= ESPERA_AUTO:
        decidiu = "nenhuma rede automática apareceu: virando hotspot"
    if not decidiu:
        return None
    try:
        os.makedirs(os.path.dirname(FLAG_AUTO), exist_ok=True)
        open(FLAG_AUTO, "w").close()
    except OSError:
        pass
    if not decidiu.startswith("nenhuma"):
        return None
    r = mode_hotspot()
    return {"ok": r["ok"], "motivo": decidiu, "erro": r.get("erro")}


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
    em_hotspot = modo_wifi() == "hotspot"
    if em_hotspot:
        return ultima_busca_wifi()
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
    # o wcn36xx não aceita duas interfaces ao mesmo tempo ('interface
    # combinations are not supported'): com o hotspot no ar, todo scan volta
    # 'Operation not supported', inclusive o ap-force
    if redes:
        aviso = ""
    elif em_hotspot:
        aviso = ("Com o hotspot ligado, o Wi-Fi do dongle não consegue procurar "
                 "redes (limitação do chip). Digite o nome da rede ou escolha "
                 "uma rede salva.")
    else:
        aviso = "Nenhuma rede encontrada por perto."
    return {"ok": True, "redes": redes[:20], "aviso": aviso, "em_hotspot": em_hotspot}


# O wcn36xx não aceita duas interfaces ao mesmo tempo ('interface
# combinations are not supported'): com o hotspot no ar, todo scan volta
# 'Operation not supported'. A saída é pausar o hotspot: parar o hostapd
# devolve o wlan0 ao modo cliente (e o tira da bridge), o scan leva ~1 s e o
# hostapd volta — ~2 s sem hotspot, medido no aparelho.
BUSCA_WIFI_JSON = "/run/opendongle/wifi-busca.json"
UNIT_BUSCA_WIFI = "opendongle-wifi-busca"


def ultima_busca_wifi():
    """Resultado da última busca com o hotspot pausado, e se há uma rodando."""
    try:
        with open(BUSCA_WIFI_JSON) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    redes = d.get("redes", [])
    return {"ok": True, "redes": redes, "em_hotspot": True,
            "quando": d.get("quando", 0), "buscando": aplic._ativo(UNIT_BUSCA_WIFI),
            "aviso": d.get("erro", "") or ("" if redes or not d else
                                            "Nenhuma rede encontrada por perto.")}


def iniciar_busca_wifi():
    """Dispara escanear_wifi() numa unit própria: quem está no hotspot perde a
    conexão por alguns segundos, e a busca tem que terminar — e religar o
    hotspot — mesmo sem ninguém esperando a resposta."""
    if aplic._ativo(UNIT_BUSCA_WIFI):
        return {"ok": True, "aviso": "Busca já em andamento."}
    cli = os.path.join(os.path.dirname(os.path.abspath(__file__)), "opendongle_cli.py")
    rc, _, err = _run(["systemd-run", "--collect", "--unit", UNIT_BUSCA_WIFI,
                       sys.executable, cli, "wifi", "--escanear"], 15)
    if rc != 0:
        return {"ok": False, "erro": f"Não iniciou a busca: {err[:160]}"}
    return {"ok": True, "aviso": "Buscando redes: o hotspot some por alguns segundos."}


def _religar_hotspot(prazo=40):
    """Religa o hostapd e espera ele voltar. Numa vez (não reproduzida) o job
    ficou 30 s parado em 'Starting' sem nada no journal: se passar de 5 s,
    registra a fila de jobs do systemd, que é o que faltou pra achar a causa.
    Vai pro journal desta unit (opendongle-wifi-busca)."""
    t0 = time.monotonic()
    _run(["systemctl", "start", "--no-block", aplic.SVC_AP], 10)
    registrou = False
    while time.monotonic() - t0 < prazo:
        if aplic._ativo(aplic.SVC_AP):
            break
        if not registrou and time.monotonic() - t0 > 5:
            _, fila, _ = _run(["systemctl", "list-jobs", "--no-pager"], 5)
            print(f"hotspot demorando a voltar ({time.monotonic() - t0:.0f} s); "
                  f"fila do systemd:\n{fila}", flush=True)
            registrou = True
        time.sleep(0.5)
    duracao = time.monotonic() - t0
    if duracao > 5:
        print(f"hotspot voltou em {duracao:.1f} s", flush=True)
    return duracao


def escanear_wifi(folga=1.5):
    """Busca de verdade. Em hotspot, pausa o hostapd pelo tempo do scan.
    'folga' deixa a resposta HTTP de quem pediu sair antes do hotspot cair."""
    em_hotspot = modo_wifi() == "hotspot"
    redes, erro = [], ""
    try:
        if em_hotspot:
            # rede de segurança: se este processo morrer no meio, o hotspot
            # volta sozinho (start num serviço já ativo não faz nada)
            _run(["systemd-run", "--collect", "--on-active=60",
                  f"--unit={UNIT_BUSCA_WIFI}-guarda", "systemctl", "start", aplic.SVC_AP], 10)
            time.sleep(folga)
            _run(["systemctl", "stop", aplic.SVC_AP], 20)
        # no boot (antes do hostapd) o wlan0 ainda está desligado
        _run(["ip", "link", "set", IFACE_WIFI, "up"], 5)
        for _ in range(3):
            redes = _listar_wifi_iw()
            if redes:
                break
            time.sleep(1)
    except Exception as e:           # o hotspot volta de qualquer jeito
        erro = f"A busca falhou: {e}"
    finally:
        if em_hotspot:
            _religar_hotspot()
            _run(["systemctl", "stop", f"{UNIT_BUSCA_WIFI}-guarda.timer"], 10)
    proprio = _ssid_hotspot()
    redes = sorted((r for r in redes if r["ssid"] != proprio), key=lambda r: -r["sinal"])[:20]
    os.makedirs(os.path.dirname(BUSCA_WIFI_JSON), exist_ok=True)
    with open(BUSCA_WIFI_JSON + ".tmp", "w") as f:
        json.dump({"quando": time.time(), "redes": redes, "erro": erro}, f, ensure_ascii=False)
    os.replace(BUSCA_WIFI_JSON + ".tmp", BUSCA_WIFI_JSON)
    return {"ok": not erro, "redes": redes, **({"erro": erro} if erro else {})}


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


def _particao_por_nome(nome):
    """Caminho do /dev da partição com esse PARTNAME (a numeração varia
    entre revisões, então nunca chutamos mmcblk0pN)."""
    for uevent in glob.glob("/sys/block/*/*/uevent"):
        try:
            with open(uevent) as f:
                campos = dict(l.strip().split("=", 1) for l in f if "=" in l)
        except OSError:
            continue
        if campos.get("PARTNAME") == nome and campos.get("DEVNAME"):
            return "/dev/" + campos["DEVNAME"]
    return None


def modem_firmware_ok():
    """False quando a partição 'modem' está vazia (zerada): sem ela o
    msm-firmware-loader não monta nada, o DSP não recebe firmware e o modem
    sobe em 'factory-test' — SIM é lido, mas não há rádio. Acontece quando o
    flash da imagem passa por cima das partições de rádio sem restaurá-las.
    None = não deu pra saber (sem permissão ou partição ausente)."""
    dev = _particao_por_nome("modem")
    if not dev:
        return None
    try:
        with open(dev, "rb") as f:
            amostra = f.read(65536)
    except OSError:
        return None
    return any(amostra)      # só zeros = firmware apagado


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

    mcc_mnc = _home_mccmnc()
    fw = modem_firmware_ok()
    diagnostico = ""
    if fw is False:
        diagnostico = ("O firmware do modem não está instalado (a partição de "
                       "rádio está vazia). O chip é lido, mas não há sinal. "
                       "É preciso restaurar o backup das partições do modem.")
    elif not registrado and modo_op and modo_op not in ("online",):
        diagnostico = (f"O modem está em modo '{modo_op}', não em 'online' — "
                       "por isso não procura rede.")
    return {"ok": True, "presente": True, "sim_presente": sim_presente,
            "mcc_mnc": mcc_mnc, "firmware_ok": fw, "diagnostico": diagnostico,
            "modo_operacao": modo_op, "registrado": registrado,
            "operadora": operadora, "rssi_dbm": rssi, "imei": imei}


def modem_online():
    """Garante o rádio ligado: o modem pode subir em 'low-power'/'offline' e
    aí nunca procura rede. Antes só líamos esse modo, nunca o corrigíamos."""
    _, out, _ = _qmi(["--dms-get-operating-mode"])
    modo = _campo(out, "Mode")
    if modo == "online":
        return {"ok": True, "mudou": False, "modo": modo}
    if modem_firmware_ok() is False:
        return {"ok": False, "erro": "Sem firmware de modem: não dá para ligar o rádio."}
    rc, _, _ = _qmi(["--dms-set-operating-mode=online"])
    if rc != 0:
        return {"ok": False, "erro": f"Não consegui ligar o rádio (modo '{modo}')."}
    return {"ok": True, "mudou": True, "modo": "online"}


def modem_reconectar():
    """Reaplica o usb-role-autosense.sh inteiro — idempotente (grupos/BT/
    LEDs não têm efeito colateral de reaplicar) e refaz o setup 4G com a
    tabela de APN atual. Antes disso, garante o rádio ligado."""
    if modem_firmware_ok() is False:
        return {"ok": False, "erro": "O firmware do modem não está instalado "
                "(partição de rádio vazia). Restaure o backup das partições do "
                "modem — sem isso não há 4G."}
    r = modem_online()
    rc, _, err = _run(["systemctl", "restart", "usb-role-autosense.service"],
                      timeout=30)
    if rc != 0:
        return {"ok": False, "erro": f"Falha ao reiniciar: {err[:120]}"}
    extra = " O rádio foi ligado." if r.get("mudou") else ""
    return {"ok": True, "aviso": f"Reconectando — pode levar alguns segundos.{extra}"}


def _home_mccmnc():
    """Código MCC-MNC da operadora do SIM (ex.: '724-10'), via qmi. É a chave
    do APN por operadora. Vazio se o SIM não responder."""
    rc, out, _ = _qmi(["--nas-get-home-network"])
    if rc != 0:
        return ""
    mcc = _campo(out, "MCC")
    mnc = _campo(out, "MNC")
    mcc = "".join(ch for ch in mcc if ch.isdigit())
    mnc = "".join(ch for ch in mnc if ch.isdigit())
    if len(mcc) == 3 and 2 <= len(mnc) <= 3:
        return f"{mcc}-{mnc}"
    return ""


def modem_apn_auto(apn):
    """APN pra operadora do SIM atual, sem a pessoa precisar saber o MCC-MNC."""
    mcc_mnc = _home_mccmnc()
    if not mcc_mnc:
        return {"ok": False, "erro": "Não consegui identificar a operadora do "
                "chip. Confira se o chip está inserido e reconhecido."}
    return modem_set_apn(mcc_mnc, apn)


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
def _erro_senha(senha):
    if len(senha) < 6:
        return "Use ao menos 6 caracteres."
    if any(ord(c) < 32 or ord(c) == 127 for c in senha):
        return "A senha não pode ter quebra de linha nem caracteres de controle."
    return None


def set_password(nova):
    erro = _erro_senha(nova)
    if erro:
        return {"ok": False, "erro": erro}
    # chpasswd lê "user:senha" do stdin (rodamos como root)
    rc, _, err = _run(["chpasswd"], entrada=f"{admin_usuario()}:{nova}\n")
    if rc != 0:
        return {"ok": False, "erro": f"Falha ao trocar senha: {err[:120]}"}
    return {"ok": True, "aviso": "Senha de administração atualizada."}


def admin_usuario():
    try:
        return pwd.getpwuid(ADMIN_UID).pw_name
    except KeyError:
        return "user"


_RE_USUARIO = re.compile(r"^[a-z][a-z0-9_-]{2,31}$")
_NOMES_RESERVADOS = {"root", "admin", "daemon", "bin", "sys", "sync", "games", "man", "lp",
                     "mail", "news", "uucp", "proxy", "backup", "list", "irc", "nobody",
                     "sudo", "adm", "wheel", "staff", "users", "opendongle", "debian-tor"}


def _sem_processos(uid, espera=10):
    for _ in range(espera * 2):
        rc, _, _ = _run(["pgrep", "-u", str(uid)], 5)
        if rc != 0:
            return True
        time.sleep(0.5)
    _run(["pkill", "-KILL", "-u", str(uid)], 5)
    time.sleep(1)
    return _run(["pgrep", "-u", str(uid)], 5)[0] != 0


def _erro_nome_usuario(novo):
    """Motivo pelo qual 'novo' não serve pra renomear o admin (None = serve)."""
    if not _RE_USUARIO.match(novo):
        return "Use de 3 a 32 letras minúsculas, números, - ou _, começando por uma letra."
    if novo in _NOMES_RESERVADOS:
        return f"'{novo}' é um nome reservado do sistema."
    try:
        pwd.getpwnam(novo)
        return f"Já existe um usuário chamado {novo}."
    except KeyError:
        pass
    if _run(["getent", "group", novo], 5)[0] == 0:
        return f"Já existe um grupo chamado {novo}."
    if os.path.exists(f"/home/{novo}"):
        return f"A pasta /home/{novo} já existe."
    return None


def renomear_usuario(novo, destacar=True):
    """Renomeia o usuário de administração (nome, grupo, pasta pessoal).
    O UID não muda: sudo (grupo 'sudo'), senha e chaves SSH continuam valendo.
    Encerra as sessões desse usuário: o usermod não renomeia com ele logado."""
    antigo = admin_usuario()
    novo = (novo or "").strip()
    if novo == antigo:
        return {"ok": False, "erro": f"O usuário já se chama {antigo}."}
    erro = _erro_nome_usuario(novo)
    if erro:
        return {"ok": False, "erro": erro}
    casa_antiga = pwd.getpwuid(ADMIN_UID).pw_dir
    casa_nova = f"/home/{novo}"
    linger = os.path.exists(f"/var/lib/systemd/linger/{antigo}")

    # pedido de dentro de uma sessão desse usuário (ssh + sudo): encerrar as
    # sessões mataria o próprio processo no meio; roda fora dela, pelo systemd
    try:
        dentro = f"user-{ADMIN_UID}.slice" in open("/proc/self/cgroup").read()
    except OSError:
        dentro = False
    if dentro and destacar:
        rc, _, err = _run(["systemd-run", "--collect", "--unit", "opendongle-renomear-usuario",
                           sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                        "opendongle_cli.py"),
                           "usuario", "--novo", novo], 20)
        if rc != 0:
            return {"ok": False, "erro": f"Não iniciou a renomeação: {err[:160]}"}
        return {"ok": True, "aviso": f"Renomeando para {novo}: esta sessão SSH vai cair em "
                                     f"instantes. Entre de novo como {novo}@ (a senha é a mesma)."}

    _run(["loginctl", "terminate-user", str(ADMIN_UID)], 15)
    _run(["systemctl", "stop", f"user@{ADMIN_UID}.service"], 30)
    if not _sem_processos(ADMIN_UID):
        return {"ok": False, "erro": "Ainda há programas rodando como esse usuário; tente de novo."}

    mover = ["-d", casa_nova, "-m"] if casa_antiga == f"/home/{antigo}" else []
    rc, _, err = _run(["usermod", "-l", novo] + mover + [antigo], 120)
    if rc != 0:
        return {"ok": False, "erro": f"Não renomeou: {err[:160]}"}
    grupo = _run(["getent", "group", antigo], 5)
    if grupo[0] == 0 and grupo[1].split(":")[2] == str(ADMIN_UID):
        rc, _, err = _run(["groupmod", "-n", novo, antigo], 30)
        if rc != 0:   # volta o usuário pra não deixar pela metade
            _run(["usermod", "-l", antigo] + (["-d", casa_antiga, "-m"] if mover else []) + [novo], 120)
            return {"ok": False, "erro": f"Não renomeou o grupo: {err[:160]}"}
    # sobras que o usermod não trata em todas as versões
    for arq in ("/etc/subuid", "/etc/subgid"):
        try:
            linhas = open(arq).read().splitlines(keepends=True)
            trocadas = [novo + l[len(antigo):] if l.startswith(antigo + ":") else l for l in linhas]
            if trocadas != linhas:
                with open(arq, "w") as f:
                    f.writelines(trocadas)
        except OSError:
            pass
    cron = f"/var/spool/cron/crontabs/{antigo}"
    if os.path.exists(cron):
        os.rename(cron, f"/var/spool/cron/crontabs/{novo}")
    if linger:
        try:
            os.remove(f"/var/lib/systemd/linger/{antigo}")
        except OSError:
            pass
        _run(["loginctl", "enable-linger", novo], 15)
    return {"ok": True, "aviso": f"Usuário renomeado de {antigo} para {novo}. "
                                 f"No SSH, entre como {novo}@ (a senha é a mesma)."}


# --------------------------------------------------------------- primeiro uso
# O repositório entrega o dongle com user/1. Quem instala pelo USB sabe o que
# faz; quem liga o dongle na tomada (modo host) com a senha de fábrica é o
# usuário final, e o painel pede um cadastro antes de qualquer outra coisa.
SENHA_FABRICA = "1"
ROLE_SW = "/sys/class/usb_role/ci_hdrc.0-role-switch/role"
_RE_NOME_PESSOA = re.compile(r"^[^\W\d_]+(?:[ '.-][^\W\d_]+)*$")


def modo_host():
    try:
        with open(ROLE_SW) as f:
            return f.read().strip() == "host"
    except OSError:
        return False


def nome_completo():
    try:
        return pwd.getpwuid(ADMIN_UID).pw_gecos.split(",")[0].strip()
    except KeyError:
        return ""


def cadastro_inicial(senha_root, nome, sobrenome, usuario, senha):
    """Valida tudo antes de mudar qualquer coisa. 'etapa' diz em qual passo
    do cadastro está o erro (1 root, 2 nome, 3 usuário e senha)."""
    nome, sobrenome, usuario = (nome or "").strip(), (sobrenome or "").strip(), (usuario or "").strip()
    senha_root, senha = senha_root or "", senha or ""
    erro = lambda etapa, texto: {"ok": False, "etapa": etapa, "erro": texto}
    if _erro_senha(senha_root):
        return erro(1, _erro_senha(senha_root))
    if senha_root == SENHA_FABRICA:
        return erro(1, "Escolha uma senha diferente da de fábrica.")
    for rotulo, valor in (("Nome", nome), ("Sobrenome", sobrenome)):
        if not valor or len(valor) > 40 or not _RE_NOME_PESSOA.match(valor):
            return erro(2, f"{rotulo}: use só letras (até 40), sem números ou símbolos.")
    atual = admin_usuario()
    if usuario != atual and _erro_nome_usuario(usuario):
        return erro(3, _erro_nome_usuario(usuario))
    if _erro_senha(senha):
        return erro(3, _erro_senha(senha))
    if senha == SENHA_FABRICA:
        return erro(3, "Escolha uma senha diferente da de fábrica.")
    if senha == senha_root:
        return erro(3, "Use uma senha diferente da senha do root.")

    if usuario != atual:
        r = renomear_usuario(usuario, destacar=False)
        if not r["ok"]:
            return erro(3, r["erro"])
    rc, _, err = _run(["usermod", "-c", f"{nome} {sobrenome}", usuario], 20)
    if rc != 0:
        return erro(2, f"Não gravou o nome: {err[:120]}")
    rc, _, err = _run(["chpasswd"], entrada=f"root:{senha_root}\n")
    if rc != 0:
        return erro(1, f"Não trocou a senha do root: {err[:120]}")
    # por último: enquanto a senha do usuário for a de fábrica, o cadastro
    # continua aparecendo e dá pra refazer o que faltou
    r = set_password(senha)
    if not r["ok"]:
        return erro(3, r["erro"])
    return {"ok": True, "usuario": usuario, "nome": nome,
            "aviso": f"Cadastro concluído. Usuário {usuario}."}


# --------------------------------------------------------------- FOTO DO PERFIL
AVATAR = "/etc/opendongle/avatar"          # bytes crus; .tipo guarda o content-type
MAX_AVATAR = 300 * 1024


def avatar_set(dataurl):
    """Salva a foto do administrador. Recebe um data URL (o front redimensiona
    para 256x256 antes de enviar). Só PNG/JPEG, até 300 KB."""
    try:
        cab, _, b64 = (dataurl or "").partition(",")
        if "base64" not in cab:
            return {"ok": False, "erro": "Formato de imagem inválido."}
        raw = base64.b64decode(b64, validate=True)
    except Exception:
        return {"ok": False, "erro": "Imagem inválida."}
    if len(raw) > MAX_AVATAR:
        return {"ok": False, "erro": "Imagem muito grande (máx. 300 KB)."}
    png = raw[:8] == b"\x89PNG\r\n\x1a\n"
    jpg = raw[:3] == b"\xff\xd8\xff"
    if not (png or jpg):
        return {"ok": False, "erro": "Envie um arquivo PNG ou JPEG."}
    try:
        os.makedirs(os.path.dirname(AVATAR), mode=0o755, exist_ok=True)
        tmp = AVATAR + ".tmp"
        with open(tmp, "wb") as f:
            f.write(raw)
        os.replace(tmp, AVATAR)
        with open(AVATAR + ".tipo", "w") as f:
            f.write("image/png" if png else "image/jpeg")
    except OSError as e:
        return {"ok": False, "erro": f"Não gravou a foto: {e}"}
    return {"ok": True, "aviso": "Foto atualizada."}


def avatar_rm():
    for caminho in (AVATAR, AVATAR + ".tipo"):
        try:
            os.unlink(caminho)
        except OSError:
            pass
    return {"ok": True, "aviso": "Foto removida."}


def avatar_tem():
    return os.path.exists(AVATAR)


def avatar_bytes():
    """(bytes, content-type) da foto, ou (None, None) se não houver."""
    try:
        with open(AVATAR, "rb") as f:
            raw = f.read()
    except OSError:
        return None, None
    try:
        with open(AVATAR + ".tipo") as f:
            tipo = f.read().strip() or "image/png"
    except OSError:
        tipo = "image/png"
    return raw, tipo


# --------------------------------------------------------------- dispatch
# Usado pela CLI. A web importa as funções diretamente.
ACOES = {
    "status": lambda a: status(),
    "set-hotspot": lambda a: set_hotspot(a.get("ssid"), a.get("senha")),
    "mode-hotspot": lambda a: mode_hotspot(),
    "connect-wifi": lambda a: connect_wifi(a.get("ssid"), a.get("senha")),
    "list-wifi": lambda a: listar_wifi(),
    "set-password": lambda a: set_password(a.get("senha", "")),
    "renomear-usuario": lambda a: renomear_usuario(a.get("nome", "")),
    "config-show": lambda a: config_show(),
    "config-aplicar": lambda a: config_aplicar(),
    "backup": lambda a: backup(),
    "restaurar": lambda a: restaurar(a.get("texto", "")),
    "reset": lambda a: reset(),
    "wifi-reconectar": lambda a: reconectar_wifi(),
    "avatar-set": lambda a: avatar_set(a.get("foto", "")),
    "avatar-rm": lambda a: avatar_rm(),
    "modem-apn": lambda a: modem_apn_auto(a.get("apn", "")),
    "modem-reconectar": lambda a: modem_reconectar(),
    "modem-online": lambda a: modem_online(),
    "list-wifi": lambda a: listar_wifi(),
    "wifi-conhecidas": lambda a: redes_conhecidas(),
    "wifi-buscar": lambda a: iniciar_busca_wifi(),
    "wifi-esquecer": lambda a: esquecer_rede(a.get("ssid")),
    "wifi-auto": lambda a: wifi_auto(a.get("ativo"), a.get("todas"),
                                     a.get("marcadas")),
    "rede-inicial": lambda a: aplic.preparar_boot(),
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
