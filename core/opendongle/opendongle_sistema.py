#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongle_sistema.py — Geral: hora, espaço, desempenho, hardware, atualizações
================================================================================
Motor da categoria Geral (modelo do Ajustes do Tarsila), usado pelo painel e
pela CLI. Leitura de /proc e /sys sempre que possível, sem subprocess.

O que demora (varrer o disco, apt) roda como unit temporária do systemd e
grava o resultado em /run/opendongle: o painel pode dormir enquanto isso
acontece, e a página só lê o arquivo.
"""

import glob
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

RUN = "/run/opendongle"
ESPACO_JSON = f"{RUN}/espaco.json"
ATUALIZACOES_JSON = f"{RUN}/atualizacoes.json"
UNIT_ESPACO = "opendongle-espaco"
UNIT_ATUALIZACAO = "opendongle-atualizacao"


def _run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", f"comando não encontrado: {cmd[0]}"


def _ler(caminho, padrao=""):
    try:
        with open(caminho) as f:
            return f.read().strip()
    except OSError:
        return padrao


def _gravar_json(caminho, dados):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho + ".tmp", "w") as f:
        json.dump(dados, f, ensure_ascii=False)
    os.replace(caminho + ".tmp", caminho)


def _ler_json(caminho):
    try:
        with open(caminho) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _unit_ativa(nome):
    return _run(["systemctl", "is-active", "--quiet", f"{nome}.service"])[0] == 0


def _disparar(unit, *args):
    """Roda este módulo como unit temporária (sobrevive ao painel dormir)."""
    if _unit_ativa(unit):
        return False
    _run(["systemctl", "reset-failed", f"{unit}.service"])
    _run(["systemd-run", f"--unit={unit}", "--collect", "--nice=10",
          "--property=IOSchedulingClass=idle", "/usr/bin/python3",
          os.path.abspath(__file__)] + list(args))
    return True


# --------------------------------------------------------------- DATA E HORA
# Do Tarsila: uma cidade por faixa horária, não os ~500 fusos do sistema. O
# deslocamento é calculado na hora (sem horário de verão), não escrito aqui.
FUSOS = [
    ("Pacific/Pago_Pago", "Pago Pago"), ("Pacific/Honolulu", "Honolulu"),
    ("America/Anchorage", "Anchorage"), ("America/Los_Angeles", "Los Angeles"),
    ("America/Denver", "Denver"), ("America/Mexico_City", "Cidade do México"),
    ("America/Rio_Branco", "Rio Branco"), ("America/Manaus", "Manaus"),
    ("America/Sao_Paulo", "São Paulo"), ("America/Noronha", "Fernando de Noronha"),
    ("Atlantic/Azores", "Açores"), ("Europe/London", "Londres"),
    ("Europe/Paris", "Paris"), ("Europe/Athens", "Atenas"),
    ("Europe/Moscow", "Moscou"), ("Asia/Dubai", "Dubai"),
    ("Asia/Karachi", "Carachi"), ("Asia/Dhaka", "Daca"),
    ("Asia/Bangkok", "Bangkok"), ("Asia/Shanghai", "Xangai"),
    ("Asia/Tokyo", "Tóquio"), ("Australia/Sydney", "Sydney"),
    ("Pacific/Noumea", "Numeá"), ("Pacific/Auckland", "Auckland"),
]


def _deslocamento(zona):
    """Fuso BASE da zona (sem horário de verão), em minutos: "GMT-3" fica
    GMT-3 o ano todo, como Windows e Android rotulam."""
    try:
        agora = datetime.now(dt_timezone.utc).astimezone(ZoneInfo(zona))
    except Exception:
        return None
    desloc, verao = agora.utcoffset(), agora.dst()
    if desloc is None:
        return None
    if verao:
        desloc -= verao
    return int(desloc.total_seconds()) // 60


def listar_fusos(atual=""):
    escolhas = list(FUSOS)
    if atual and atual not in dict(escolhas):
        escolhas.append((atual, atual.split("/")[-1].replace("_", " ")))
    itens = []
    for zona, cidade in escolhas:
        minutos = _deslocamento(zona)
        if minutos is None:
            continue
        horas, resto = divmod(abs(minutos), 60)
        itens.append((minutos, zona, "(GMT%s%02d:%02d) %s" % (
            "+" if minutos >= 0 else "-", horas, resto, cidade)))
    itens.sort(key=lambda t: (t[0], t[2]))
    return [(z, rot) for _, z, rot in itens]


def hora_status():
    _, out, _ = _run(["timedatectl", "show", "-p", "Timezone", "-p", "NTP",
                      "-p", "NTPSynchronized"])
    campos = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    return {"ok": True, "agora": datetime.now().astimezone().strftime("%d/%m/%Y %H:%M:%S"),
            "fuso": campos.get("Timezone", ""), "automatica": campos.get("NTP") == "yes",
            "sincronizada": campos.get("NTPSynchronized") == "yes",
            "fusos": listar_fusos(campos.get("Timezone", ""))}


def hora_manual(data, hora):
    """data AAAA-MM-DD e hora HH:MM (formato dos campos date/time do HTML)."""
    try:
        quando = datetime.strptime(f"{data} {hora}", "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return {"ok": False, "erro": "Data ou hora inválida."}
    if hora_status()["automatica"]:
        return {"ok": False, "erro": "Desligue a hora automática antes de ajustar na mão "
                "(senão a internet desfaz o ajuste em segundos)."}
    rc, _, err = _run(["timedatectl", "set-time", quando.strftime("%Y-%m-%d %H:%M:00")])
    if rc != 0:
        return {"ok": False, "erro": f"Não ajustou: {err[:120]}"}
    return {"ok": True, "aviso": f"Hora ajustada para {quando.strftime('%d/%m/%Y %H:%M')}."}


# --------------------------------------------------------------- CONTA
def sessoes():
    """Sessões abertas no sistema (SSH e console serial)."""
    rc, out, _ = _run(["loginctl", "list-sessions", "--json=short"], timeout=10)
    try:
        lista = json.loads(out) if rc == 0 else []
    except ValueError:
        lista = []
    saida = []
    for s in lista:
        if s.get("class") != "user":
            continue
        _, info, _ = _run(["loginctl", "show-session", str(s.get("session")), "-p",
                           "RemoteHost", "-p", "Service", "-p", "Timestamp", "-p", "State"],
                           timeout=5)
        campos = dict(l.split("=", 1) for l in info.splitlines() if "=" in l)
        if campos.get("State") == "closing":   # já encerrada, esperando processos saírem
            continue
        saida.append({"id": str(s.get("session")), "usuario": s.get("user", ""),
                      "tty": s.get("tty") or "", "servico": campos.get("Service", ""),
                      "origem": campos.get("RemoteHost", ""), "desde": campos.get("Timestamp", "")})
    return {"ok": True, "sessoes": saida}


def encerrar_sessao(sessao_id):
    sessao_id = str(sessao_id or "")
    if not any(x["id"] == sessao_id for x in sessoes()["sessoes"]):
        return {"ok": False, "erro": "Sessão não encontrada (talvez já tenha saído)."}
    rc, _, err = _run(["loginctl", "terminate-session", sessao_id], timeout=15)
    if rc != 0:
        return {"ok": False, "erro": f"Não encerrou: {err[:120]}"}
    return {"ok": True, "aviso": "Sessão encerrada."}


# --------------------------------------------------------------- ESPAÇO
def _du_kb(caminho):
    rc, out, _ = _run(["du", "-sk", caminho], timeout=60)
    try:
        return int(out.split()[0]) if rc == 0 else 0
    except (ValueError, IndexError):
        return 0


def _logs_rotacionados():
    return [p for p in glob.glob("/var/log/**/*", recursive=True)
            if os.path.isfile(p) and re.search(r"\.(gz|xz|\d+)$", p)]


def espaco_status():
    discos = []
    for ponto, nome in (("/", "Sistema"), ("/boot", "Boot")):
        try:
            st = os.statvfs(ponto)
        except OSError:
            continue
        total = st.f_blocks * st.f_frsize
        livre = st.f_bavail * st.f_frsize
        if total:
            discos.append({"nome": nome, "ponto": ponto, "total_mb": total // 2**20,
                           "livre_mb": livre // 2**20,
                           "usado_pct": round((total - livre) / total * 100)})
    _, jornal, _ = _run(["journalctl", "--disk-usage"], timeout=15)
    m = re.search(r"take up ([\d.]+)([KMG])", jornal)
    jornal_mb = (float(m.group(1)) * {"K": 1 / 1024, "M": 1, "G": 1024}[m.group(2)]) if m else 0
    logs_kb = sum(os.path.getsize(p) for p in _logs_rotacionados()) // 1024
    return {"ok": True, "discos": discos,
            "liberavel": {"cache_apt_mb": _du_kb("/var/cache/apt/archives") // 1024,
                          "logs_antigos_mb": logs_kb // 1024,
                          "journal_mb": round(jornal_mb, 1)},
            "analise": _ler_json(ESPACO_JSON),
            "analisando": _unit_ativa(UNIT_ESPACO)}


def espaco_analisar():
    if not _disparar(UNIT_ESPACO, "espaco"):
        return {"ok": True, "aviso": "A análise já está em andamento."}
    return {"ok": True, "aviso": "Analisando o disco em segundo plano (leva alguns segundos)."}


def _trabalho_espaco():
    """Maiores pastas até 3 níveis, só no disco do sistema (-x)."""
    rc, out, _ = _run(["du", "-x", "-k", "-d", "3", "/"], timeout=600)
    pastas = []
    for linha in out.splitlines():
        partes = linha.split("\t", 1)
        if len(partes) == 2 and partes[0].isdigit() and partes[1] != "/":
            pastas.append({"caminho": partes[1], "mb": round(int(partes[0]) / 1024, 1)})
    pastas.sort(key=lambda p: -p["mb"])
    _gravar_json(ESPACO_JSON, {"quando": time.time(), "pastas": pastas[:15]})


def espaco_liberar():
    antes = os.statvfs("/")
    _run(["apt-get", "clean"], timeout=120)
    _run(["journalctl", "--vacuum-size=8M"], timeout=60)
    for p in _logs_rotacionados():
        try:
            os.unlink(p)
        except OSError:
            pass
    depois = os.statvfs("/")
    ganho = (depois.f_bavail - antes.f_bavail) * depois.f_frsize // 2**20
    return {"ok": True, "aviso": f"Liberados {max(ganho, 0)} MB."}


# --------------------------------------------------------------- DESEMPENHO
_ANTERIOR = {}   # última amostra, pra calcular % de CPU entre duas leituras
# nunca encerrar pelo painel: sem eles o dongle perde rede, acesso ou modem
PROTEGIDOS = re.compile(r"^(systemd.*|init|sshd.*|dnsmasq|hostapd|wpa_supplicant|"
                        r"rmtfs|qrtr-ns|dbus-daemon|earlyoom|kthreadd|python3)$")


def _cpu_por_nucleo():
    nucleos = {}
    for linha in _ler("/proc/stat").splitlines():
        if linha.startswith("cpu") and linha[3:4].isdigit():
            p = linha.split()
            valores = list(map(int, p[1:8]))
            nucleos[p[0]] = (sum(valores), valores[3] + valores[4])   # total, ocioso
    return nucleos


def _processos():
    lista = {}
    pagina_kb = os.sysconf("SC_PAGE_SIZE") // 1024
    for d in glob.glob("/proc/[0-9]*"):
        try:
            with open(f"{d}/stat") as f:
                bruto = f.read()
            nome = bruto[bruto.index("(") + 1:bruto.rindex(")")]
            campos = bruto[bruto.rindex(")") + 2:].split()
            rss_kb = int(campos[21]) * pagina_kb
            if rss_kb == 0:
                continue   # thread de kernel
            lista[int(d[6:])] = {"nome": nome, "ticks": int(campos[11]) + int(campos[12]),
                                 "rss_kb": rss_kb}
        except (OSError, ValueError, IndexError):
            continue
    return lista


def desempenho():
    agora = time.monotonic()
    cpu = _cpu_por_nucleo()
    procs = _processos()
    ant = _ANTERIOR.get("dados")
    intervalo = agora - _ANTERIOR.get("quando", agora)
    hz = os.sysconf("SC_CLK_TCK")

    nucleos = []
    for nome in sorted(cpu, key=lambda n: int(n[3:])):
        pct = None
        if ant and nome in ant["cpu"]:
            dt = cpu[nome][0] - ant["cpu"][nome][0]
            di = cpu[nome][1] - ant["cpu"][nome][1]
            pct = round(100 * (dt - di) / dt) if dt > 0 else 0
        freq = _ler(f"/sys/devices/system/cpu/{nome}/cpufreq/scaling_cur_freq")
        nucleos.append({"nome": nome, "pct": pct,
                        "mhz": int(freq) // 1000 if freq.isdigit() else None})

    lista = []
    for pid, p in procs.items():
        pct = None
        if ant and pid in ant["procs"] and intervalo > 0:
            pct = round(100 * (p["ticks"] - ant["procs"][pid]["ticks"]) / hz / intervalo, 1)
        lista.append({"pid": pid, "nome": p["nome"], "cpu": pct,
                      "ram_mb": round(p["rss_kb"] / 1024, 1),
                      "protegido": bool(PROTEGIDOS.match(p["nome"]))})
    lista.sort(key=lambda x: (-(x["cpu"] or 0), -x["ram_mb"]))
    _ANTERIOR.update(dados={"cpu": cpu, "procs": procs}, quando=agora)

    mem = {}
    for linha in _ler("/proc/meminfo").splitlines():
        chave, _, valor = linha.partition(":")
        if valor.strip().split()[:1] and valor.split()[0].isdigit():
            mem[chave] = int(valor.split()[0])
    zram = _ler("/sys/block/zram0/mm_stat").split()
    temps = {}
    for base in glob.glob("/sys/class/thermal/thermal_zone*"):
        t = _ler(f"{base}/temp")
        if t.lstrip("-").isdigit():
            temps[_ler(f"{base}/type", base)] = round(int(t) / 1000, 1)
    return {"ok": True, "carga": [round(x, 2) for x in os.getloadavg()], "nucleos": nucleos,
            "ram": {"total_mb": mem.get("MemTotal", 0) // 1024,
                    "disponivel_mb": mem.get("MemAvailable", 0) // 1024},
            "swap": {"total_mb": mem.get("SwapTotal", 0) // 1024,
                     "usado_mb": (mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)) // 1024},
            "zram": ({"dados_mb": int(zram[0]) // 2**20, "comprimido_mb": int(zram[1]) // 2**20}
                     if len(zram) >= 2 else None),
            "temperaturas": temps, "processos": lista[:25]}


def encerrar_processo(pid):
    try:
        pid = int(pid)
        nome = _processos()[pid]["nome"]
    except (ValueError, TypeError, KeyError):
        return {"ok": False, "erro": "Processo não encontrado."}
    if PROTEGIDOS.match(nome) or pid <= 2:
        return {"ok": False, "erro": f"{nome} é essencial pro dongle e não pode ser "
                "encerrado por aqui."}
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as e:
        return {"ok": False, "erro": f"Não encerrou: {e}"}
    return {"ok": True, "aviso": f"Pedido pra encerrar {nome} (PID {pid}) enviado."}


# --------------------------------------------------------------- HARDWARE
_EMMC_VIDA = {"0x00": "não informado", "0x01": "0–10% usado", "0x02": "10–20% usado",
              "0x03": "20–30% usado", "0x04": "30–40% usado", "0x05": "40–50% usado",
              "0x06": "50–60% usado", "0x07": "60–70% usado", "0x08": "70–80% usado",
              "0x09": "80–90% usado", "0x0a": "90–100% usado", "0x0b": "vida útil excedida"}
_EMMC_EOL = {"0x00": "não informado", "0x01": "normal", "0x02": "atenção (80% dos blocos "
             "reservas usados)", "0x03": "urgente (90% dos blocos reservas usados)"}


def hardware():
    dt = "/proc/device-tree"
    compat = _ler(f"{dt}/compatible").replace("\x00", " ").split()
    freqs = _ler("/sys/devices/system/cpu/cpu0/cpufreq/scaling_available_frequencies").split()
    emmc = next(iter(glob.glob("/sys/class/mmc_host/mmc*/mmc*:*")), "")
    setores = _ler("/sys/block/mmcblk0/size")
    vida = _ler(f"{emmc}/life_time").split() if emmc else []
    try:
        pretty = next(l.split("=", 1)[1].strip().strip('"')
                      for l in _ler("/etc/os-release").splitlines() if l.startswith("PRETTY_NAME="))
    except StopIteration:
        pretty = "Debian"
    mem_kb = next((int(l.split()[1]) for l in _ler("/proc/meminfo").splitlines()
                   if l.startswith("MemTotal")), 0)
    _, bt, _ = _run(["hciconfig", "hci0"], timeout=5)
    m_bt = re.search(r"BD Address: ([0-9A-F:]{17})", bt)
    _, rev, _ = _run(["qmicli", "-d", "/dev/wwan0qmi0", "--dms-get-revision"], timeout=10) \
        if os.path.exists("/dev/wwan0qmi0") else (1, "", "")
    _, ids, _ = _run(["qmicli", "-d", "/dev/wwan0qmi0", "--dms-get-ids"], timeout=10) \
        if os.path.exists("/dev/wwan0qmi0") else (1, "", "")
    m_rev = re.search(r"Revision:\s*'([^']+)'", rev)
    m_imei = re.search(r"IMEI:\s*'(\d+)'", ids)
    uptime = int(float(_ler("/proc/uptime", "0").split()[0]))
    return {"ok": True,
            "placa": _ler(f"{dt}/model").replace("\x00", ""),
            "compativel": compat[0] if compat else "",
            "soc": compat[-1].split(",")[-1].upper() if compat else "",
            "cpu": {"nucleos": os.cpu_count(),
                    "mhz": [int(f) // 1000 for f in freqs if f.isdigit()],
                    "governor": _ler("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")},
            "ram_mb": mem_kb // 1024,
            "emmc": {"modelo": _ler(f"{emmc}/name") if emmc else "",
                     "fabricado": _ler(f"{emmc}/date") if emmc else "",
                     "tamanho_gb": round(int(setores) * 512 / 1e9, 1) if setores.isdigit() else None,
                     "desgaste": [_EMMC_VIDA.get(v, v) for v in vida],
                     "reservas": _EMMC_EOL.get(_ler(f"{emmc}/pre_eol_info"), "não informado")
                     if emmc else ""},
            "wifi": {"driver": os.path.basename(os.path.realpath("/sys/class/net/wlan0/device/driver")),
                     "mac": _ler("/sys/class/net/wlan0/address")},
            "bluetooth_mac": m_bt.group(1) if m_bt else "",
            "usb_mac": _ler("/sys/class/net/usb0/address"),
            "modem": {"firmware": m_rev.group(1) if m_rev else "", "imei": m_imei.group(1) if m_imei else ""},
            "kernel": os.uname().release, "sistema": pretty,
            "ligado_ha": f"{uptime // 86400}d {uptime % 86400 // 3600}h {uptime % 3600 // 60}min"}


# --------------------------------------------------------------- USB
ROLE_SW = "/sys/class/usb_role/ci_hdrc.0-role-switch/role"
# classe USB (da interface) -> (emoji, tipo)
_CLASSES_USB = {"01": ("🎧", "Áudio"), "02": ("🌐", "Rede/modem"), "03": ("⌨️", "Teclado, mouse ou controle"),
                "06": ("📷", "Câmera fotográfica"), "07": ("🖨️", "Impressora"),
                "08": ("💾", "Armazenamento"), "09": ("🔀", "Hub USB"), "0a": ("🔌", "Serial"),
                "0e": ("📹", "Câmera de vídeo"), "e0": ("🔵", "Bluetooth/sem fio"),
                "ef": ("🧩", "Multifunção"), "ff": ("🧩", "Específico do fabricante")}


def usb_dispositivos():
    """Aparelhos plugados na porta USB (modo host), lidos do sysfs."""
    lista = []
    for d in sorted(glob.glob("/sys/bus/usb/devices/*")):
        nome = os.path.basename(d)
        if ":" in nome or nome.startswith("usb"):
            continue   # interfaces e o hub raiz não são aparelhos
        classes = sorted({_ler(i).lower() for i in glob.glob(f"{d}/*:*/bInterfaceClass")} - {""})
        principal = next((c for c in classes if c not in ("09", "ef", "ff")), classes[0] if classes else "")
        emoji, tipo = _CLASSES_USB.get(principal, ("🔌", "Aparelho USB"))
        lista.append({"emoji": emoji, "tipo": tipo,
                      "nome": " ".join(x for x in (_ler(f"{d}/manufacturer"), _ler(f"{d}/product")) if x)
                      or f"{_ler(f'{d}/idVendor')}:{_ler(f'{d}/idProduct')}",
                      "id": f"{_ler(f'{d}/idVendor')}:{_ler(f'{d}/idProduct')}",
                      "velocidade": _ler(f"{d}/speed")})
    return {"ok": True, "papel": _ler(ROLE_SW), "aparelhos": lista}


def usb_papel(novo):
    """Troca na hora o papel da porta (vale até o próximo boot, quando o
    usb-role-autosense decide de novo)."""
    if novo not in ("host", "device"):
        return {"ok": False, "erro": "Papel inválido."}
    try:
        with open(ROLE_SW, "w") as f:
            f.write(novo)
    except OSError as e:
        return {"ok": False, "erro": f"Não trocou: {e}"}
    return {"ok": True, "aviso": "Porta em modo periférico: aparelhos USB podem ser plugados."
            if novo == "host" else "Porta em modo PC: o dongle volta a aparecer como rede USB."}


# --------------------------------------------------------------- ATUALIZAÇÕES
def atualizacoes_status():
    estado = _ler_json(ATUALIZACOES_JSON) or {"etapa": "nunca", "pendentes": None}
    estado["rodando"] = _unit_ativa(UNIT_ATUALIZACAO)
    estado["ok"] = True
    return estado


def atualizacoes_iniciar(instalar):
    if not _disparar(UNIT_ATUALIZACAO, "atualizar", "instalar" if instalar else "verificar"):
        return {"ok": False, "erro": "Já tem uma atualização em andamento."}
    return {"ok": True, "aviso": "Instalando atualizações em segundo plano…" if instalar
            else "Procurando atualizações em segundo plano…"}


def _pendentes():
    _, out, _ = _run(["apt-get", "-s", "upgrade"], timeout=300)
    return [l.split()[1] for l in out.splitlines() if l.startswith("Inst ")]


def _trabalho_atualizar(instalar):
    """Mesma lógica do tarsila-atualizar: update, conta, (upgrade), reconta."""
    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    _gravar_json(ATUALIZACOES_JSON, {"etapa": "procurando", "quando": time.time()})
    r = subprocess.run(["apt-get", "update"], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        _gravar_json(ATUALIZACOES_JSON, {"etapa": "erro", "quando": time.time(),
                                         "erro": "Sem acesso aos repositórios (o dongle precisa de internet)."})
        return
    pendentes = _pendentes()
    if not instalar or not pendentes:
        _gravar_json(ATUALIZACOES_JSON, {"etapa": "verificado", "quando": time.time(),
                                         "pendentes": len(pendentes), "pacotes": pendentes[:40]})
        return
    _gravar_json(ATUALIZACOES_JSON, {"etapa": "instalando", "quando": time.time(),
                                     "pendentes": len(pendentes), "pacotes": pendentes[:40]})
    r = subprocess.run(["apt-get", "upgrade", "-y", "-o", "Dpkg::Options::=--force-confold",
                        "-o", "Dpkg::Options::=--force-confdef"],
                       capture_output=True, text=True, env=env)
    subprocess.run(["apt-get", "clean"], capture_output=True)
    restantes = _pendentes()
    _gravar_json(ATUALIZACOES_JSON, {
        "etapa": "instalado" if r.returncode == 0 else "erro", "quando": time.time(),
        "feitas": max(len(pendentes) - len(restantes), 0), "pendentes": len(restantes),
        "erro": "" if r.returncode == 0 else (r.stderr or r.stdout)[-200:]})


# --------------------------------------------------------------- SERVIÇOS (avançadas)
# Sem eles o dongle perde rede, acesso, modem ou proteção de memória.
ESSENCIAIS = re.compile(r"^(ssh|sshd|dnsmasq|dbus|systemd-.+|hostapd@.+|wpa_supplicant@.+|"
                        r"opendongle.*|usb-role-autosense|rmtfs|qrtr-ns|msm-.+|msm8916-.+|"
                        r"nftables|earlyoom|zramswap|getty@.+|serial-getty@.+|user@.+|"
                        r"polkit|resize-rootfs|regenerate-ssh-host-keys|sshd-keygen)\.service$")
# têm tela própria, que decide quando ligar: mexer aqui brigaria com ela
GERENCIADOS = {"bluetooth.service": ("Dispositivos › Bluetooth", "/bluetooth"),
               "tor.service": ("Internet › Navegação via Tor", "/tor"),
               "tor@default.service": ("Internet › Navegação via Tor", "/tor"),
               "tailscaled.service": ("Internet › Acesso remoto", "/remoto"),
               "dnsproxy.service": ("DNS criptografado (config dns.criptografado)", "/internet"),
               "NetworkManager.service": ("rede (systemd-networkd)", "/internet"),
               "networking.service": ("rede (systemd-networkd)", "/internet"),
               "wpa_supplicant.service": ("rede (systemd-networkd)", "/internet")}
# nunca aparecem nem podem ser ligados pelo painel: debug-shell abre shell de
# root SEM senha no console; console-getty não se aplica a um dongle
OCULTOS = {"debug-shell.service", "console-getty.service"}
AVISOS_SERVICO = {"avahi-daemon.service": "Desligado, opendongle.local para de funcionar.",
                  "cron.service": "Tarefas agendadas do sistema (limpeza de logs etc.)."}


UNIT_FILES_JSON = f"{RUN}/unit-files.json"
# onde enable/disable/mask criam ou apagam links, e onde o apt instala units
PASTAS_UNITS = ("/etc/systemd/system", "/usr/lib/systemd/system", "/lib/systemd/system")


def _chave_units():
    """Muda sempre que o estado de habilitação pode ter mudado: enable/disable
    mexem nas pastas *.wants, mask cria link em /etc/systemd/system e o apt
    mexe em /usr/lib/systemd/system — em todos os casos, o mtime de alguma
    dessas pastas muda."""
    pastas = list(PASTAS_UNITS) + glob.glob("/etc/systemd/system/*.wants")
    return [os.stat(p).st_mtime_ns for p in sorted(pastas) if os.path.isdir(p)]


def _habilitacao():
    """{unit: enabled|disabled|static|...}. O 'systemctl list-unit-files' leva
    de 2 a 5 s no dongle (varre todos os arquivos de unit), então o resultado
    fica em /run até alguma pasta de units mudar."""
    chave = _chave_units()
    try:
        with open(UNIT_FILES_JSON) as f:
            cache = json.load(f)
        if cache.get("chave") == chave:
            return cache["habilitacao"]
    except (OSError, ValueError, KeyError):
        pass
    _, arquivos, _ = _run(["systemctl", "list-unit-files", "--type=service", "--no-legend",
                           "--no-pager"], 20)
    habilitacao = {}
    for linha in arquivos.splitlines():
        p = linha.split()
        if len(p) >= 2:
            habilitacao[p[0]] = p[1]
    if habilitacao:
        _gravar_json(UNIT_FILES_JSON, {"chave": chave, "habilitacao": habilitacao})
    return habilitacao


def servicos():
    """Serviços habilitados no boot ou rodando, com RAM (PSS) e se dá pra mexer."""
    habilitacao = _habilitacao()
    _, units, _ = _run(["systemctl", "list-units", "--type=service", "--all", "--no-legend",
                        "--no-pager", "--plain"], 20)
    ativos = {}
    for linha in units.splitlines():
        p = linha.split(None, 4)
        if len(p) >= 4:
            ativos[p[0]] = p[2] == "active" and p[3] == "running"
    import opendongle_engine as eng   # RAM por unit (mesma leitura do 'recursos')
    ram = {s["unit"]: s["kb"] for s in eng.recursos()["servicos"]}
    lista = []
    for nome in sorted(set(habilitacao) | {n for n, a in ativos.items() if a}):
        estado = habilitacao.get(nome, "")
        rodando = ativos.get(nome, False)
        # "disabled" entra: senão um serviço desligado por aqui some da lista e
        # não dá pra religar (visto ao vivo com o cron). static/masked/alias não.
        if not (rodando or estado in ("enabled", "disabled")) or "@." in nome or nome in OCULTOS:
            continue
        gerenciado = GERENCIADOS.get(nome)
        lista.append({"nome": nome, "habilitado": estado == "enabled", "rodando": rodando,
                      "ram_mb": round(ram.get(nome, 0) / 1024, 1),
                      "essencial": bool(ESSENCIAIS.match(nome)),
                      "gerenciado": gerenciado[0] if gerenciado else "",
                      "gerenciado_url": gerenciado[1] if gerenciado else "",
                      "aviso": AVISOS_SERVICO.get(nome, "")})
    lista.sort(key=lambda s: (s["essencial"], bool(s["gerenciado"]), -s["ram_mb"], s["nome"]))
    return {"ok": True, "servicos": lista}


def servico_set(nome, ligar):
    alvo = next((s for s in servicos()["servicos"] if s["nome"] == nome), None)
    if not alvo:
        return {"ok": False, "erro": "Serviço não encontrado."}
    if alvo["essencial"]:
        return {"ok": False, "erro": f"{nome} é essencial pro dongle e não pode ser desligado por aqui."}
    if alvo["gerenciado"]:
        return {"ok": False, "erro": f"{nome} é controlado em {alvo['gerenciado']}."}
    rc, _, err = _run(["systemctl", "enable" if ligar else "disable", "--now", nome], 60)
    if rc != 0:
        return {"ok": False, "erro": f"Não mudou: {err[:140]}"}
    return {"ok": True, "aviso": f"{nome} {'ligado e habilitado no boot' if ligar else 'parado e desabilitado no boot'}."}


# --------------------------------------------------------------- KERNEL
def kernel():
    modulos = []
    for linha in _ler("/proc/modules").splitlines():
        p = linha.split()
        if len(p) >= 4:
            usado_por = [x for x in p[3].split(",") if x and x != "-"]
            modulos.append({"nome": p[0], "kb": int(p[1]) // 1024, "usos": int(p[2]),
                            "usado_por": usado_por})
    modulos.sort(key=lambda m: m["nome"])
    carregar_no_boot = []
    for arq in sorted(glob.glob("/etc/modules-load.d/*.conf")):
        carregar_no_boot += [l.strip() for l in _ler(arq).splitlines()
                             if l.strip() and not l.startswith("#")]
    return {"ok": True, "versao": os.uname().release, "build": os.uname().version,
            "arquitetura": os.uname().machine, "cmdline": _ler("/proc/cmdline"),
            "modulos": modulos, "no_boot": carregar_no_boot}


# --------------------------------------------------------------- TAREFAS LONGAS
# Instalar pacotes (Tor, Tailscale, PipeWire) leva minutos: dentro da
# requisição do painel a conexão cai no meio (o repassador larga depois de
# 60 s sem tráfego). Vira unit temporária, e a página acompanha pelo /run.
TAREFA_JSON = f"{RUN}/tarefa.json"
UNIT_TAREFA = "opendongle-tarefa"
TAREFAS = {
    "tor": "Navegação via Tor",
    "remoto": "Acesso remoto (Tailscale)",
    "audio-bt": "Áudio Bluetooth",
}


def tarefa_iniciar(nome, **opcoes):
    if nome not in TAREFAS:
        return {"ok": False, "erro": "Tarefa desconhecida."}
    if _unit_ativa(UNIT_TAREFA):
        return {"ok": False, "erro": "Já tem uma instalação em andamento; aguarde terminar."}
    _gravar_json(TAREFA_JSON, {"nome": nome, "titulo": TAREFAS[nome], "etapa": "rodando",
                               "quando": time.time()})
    _disparar(UNIT_TAREFA, "tarefa", nome, json.dumps(opcoes))
    return {"ok": True, "aviso": f"Instalando {TAREFAS[nome]} em segundo plano. Pode levar "
            "alguns minutos; esta página atualiza sozinha."}


def tarefa_estado(nome):
    est = _ler_json(TAREFA_JSON)
    if not est or est.get("nome") != nome:
        return None
    if est.get("etapa") == "rodando" and not _unit_ativa(UNIT_TAREFA):
        est.update(etapa="erro", erro="A instalação foi interrompida.")
    return est


def _trabalho_tarefa(nome, opcoes):
    import opendongle_engine as eng   # só aqui: o engine não depende deste módulo
    try:
        if nome == "tor":
            r = eng.tor_set(True)
        elif nome == "remoto":
            r = eng.remoto_set(True, opcoes.get("lan", False), opcoes.get("saida", False))
        else:
            r = eng.audio_bt_set(True)
    except Exception as e:   # o estado precisa sair de "rodando" de qualquer jeito
        r = {"ok": False, "erro": f"Erro inesperado: {e}"}
    _gravar_json(TAREFA_JSON, {"nome": nome, "titulo": TAREFAS[nome], "quando": time.time(),
                               "etapa": "ok" if r.get("ok") else "erro",
                               "aviso": r.get("aviso", ""), "erro": r.get("erro", ""),
                               "link_login": r.get("link_login", "")})


# --------------------------------------------------------------- ENERGIA
def energia(acao):
    if acao not in ("reboot", "poweroff"):
        return {"ok": False, "erro": "Ação inválida."}
    # atraso curto: dá tempo da resposta chegar ao navegador antes de cair
    rc, _, err = _run(["systemd-run", "--on-active=3", "systemctl", acao])
    if rc != 0:
        return {"ok": False, "erro": f"Falhou: {err[:120]}"}
    return {"ok": True, "aviso": "Reiniciando em 3 segundos…" if acao == "reboot" else
            "Desligando em 3 segundos. Pra ligar de novo, tire e recoloque o dongle."}


if __name__ == "__main__":
    if sys.argv[1:2] == ["espaco"]:
        _trabalho_espaco()
    elif sys.argv[1:2] == ["atualizar"]:
        _trabalho_atualizar(sys.argv[2:3] == ["instalar"])
    elif sys.argv[1:2] == ["tarefa"]:
        _trabalho_tarefa(sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else {})
