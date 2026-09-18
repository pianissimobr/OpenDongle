#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongle_audio.py — Áudio: placas USB pelo ALSA e áudio Bluetooth sob demanda
================================================================================
O dongle não tem placa de som própria. Som de verdade vem de:

  placa de som USB  -> ALSA direto (amixer/aplay/arecord): nenhum daemon, custo
                       zero parado
  fone/caixa BT     -> PipeWire + WirePlumber como serviços do usuário, ligados
                       só quando o usuário ativa (pacotes baixados na 1ª vez)

Usado pelo painel e pela CLI.
"""

import json
import math
import os
import pwd
import re
import struct
import subprocess
import time

UID = 1000   # usuário do dongle pelo UID: o nome pode ser trocado no painel
PACOTES_BT = ["pipewire", "wireplumber", "libspa-0.2-bluetooth"]
WP_CONF_REL = ".config/wireplumber/wireplumber.conf.d/51-opendongle.conf"


def _usuario():
    return pwd.getpwuid(UID)


# Sem tela não há "seat" ativo, e por padrão o WirePlumber só liga o Bluetooth
# pra sessão que está no seat: num dongle ele nunca ligaria.
WP_CONF_CONTEUDO = """# GERADO pelo OpenDongle: aparelho sem tela, Bluetooth sem depender de seat
wireplumber.profiles = {
  main = {
    monitor.bluez.seat-monitoring = disabled
  }
}
"""
SERVICOS_USUARIO = ["pipewire.socket", "pipewire.service", "wireplumber.service"]
SERVICOS_GLOBAIS = SERVICOS_USUARIO + ["filter-chain.service"]
ASOUND_CONF = "/etc/asound.conf"
RE_ID_PLACA = re.compile(r"^[A-Za-z0-9_]{1,15}$")


def _run(cmd, timeout=15, entrada=None):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, input=entrada)
        return r.returncode, r.stdout, r.stderr.decode(errors="replace").strip()
    except subprocess.TimeoutExpired:
        return 124, b"", "timeout"
    except FileNotFoundError:
        return 127, b"", f"comando não encontrado: {cmd[0]}"


def _texto(cmd, timeout=15):
    rc, out, err = _run(cmd, timeout)
    return rc, out.decode(errors="replace").strip(), err


# --------------------------------------------------------------- ALSA (placas)
def _placas_alsa():
    """(índice, id, nome, usb) das placas reais: a Loopback do diagnóstico é
    virtual e não entra."""
    placas = []
    try:
        linhas = open("/proc/asound/cards").read().splitlines()
    except OSError:
        return placas
    for linha in linhas:
        m = re.match(r"^\s*(\d+)\s+\[(\S+)\s*\]:\s*(.*?)\s+-\s+(.*)$", linha)
        if not m or m.group(2) == "Loopback":
            continue
        indice = int(m.group(1))
        placas.append({"indice": indice, "id": m.group(2), "nome": m.group(4),
                       "usb": os.path.exists(f"/proc/asound/card{indice}/usbid")})
    return placas


def _dispositivo_alsa(indice, captura=False):
    """plughw:<placa>,<dispositivo>. Nem toda placa toca e grava no dispositivo
    0 (headsets USB costumam ter a captura em outro), então vale o que a placa
    declara em /proc/asound/cardN/pcm*p|c."""
    sufixo = "c" if captura else "p"
    try:
        nums = sorted(int(n[3:-1]) for n in os.listdir(f"/proc/asound/card{indice}")
                      if re.fullmatch(rf"pcm\d+{sufixo}", n))
    except OSError:
        nums = []
    return f"plughw:{indice},{nums[0] if nums else 0}"


def _controles(indice):
    """Controles simples do amixer com volume de reprodução ou captura."""
    _, out, _ = _texto(["amixer", "-c", str(indice), "scontents"], 10)
    controles, atual = [], None
    for linha in out.splitlines():
        m = re.match(r"^Simple mixer control '(.+)',(\d+)$", linha)
        if m:
            atual = {"nome": m.group(1), "caps": "", "volume": None, "mudo": None, "tipo": ""}
            controles.append(atual)
            continue
        if atual is None:
            continue
        linha = linha.strip()
        if linha.startswith("Capabilities:"):
            atual["caps"] = linha
        pct = re.search(r"\[(\d+)%\]", linha)
        chave = re.search(r"\[(on|off)\]", linha)
        if pct and atual["volume"] is None:
            atual["volume"] = int(pct.group(1))
        if chave and atual["mudo"] is None:
            atual["mudo"] = chave.group(1) == "off"
    saida = []
    for c in controles:
        if "pvolume" in c["caps"] or "volume" in c["caps"].split():
            c["tipo"] = "saída"
        elif "cvolume" in c["caps"]:
            c["tipo"] = "entrada"
        else:
            continue
        del c["caps"]
        saida.append(c)
    return saida


def placa_padrao_atual():
    try:
        m = re.search(r'slave\.pcm\s+"hw:([A-Za-z0-9_]+)"', open(ASOUND_CONF).read())
        return m.group(1) if m else ""
    except OSError:
        return ""


def placas():
    lista = []
    for p in _placas_alsa():
        p["controles"] = _controles(p["indice"])
        lista.append(p)
    return {"ok": True, "placas": lista, "padrao": placa_padrao_atual()}


def _placa_por_id(ident):
    return next((p for p in _placas_alsa() if p["id"] == ident), None)


def ajustar(placa_id, controle, volume=None, mudo=None):
    p = _placa_por_id(placa_id)
    if not p:
        return {"ok": False, "erro": "Placa de som não encontrada (foi desplugada?)."}
    if controle not in {c["nome"] for c in _controles(p["indice"])}:
        return {"ok": False, "erro": "Controle inválido."}
    args = []
    if volume is not None:
        try:
            volume = max(0, min(100, int(volume)))
        except (TypeError, ValueError):
            return {"ok": False, "erro": "Volume inválido."}
        args.append(f"{volume}%")
    if mudo is not None:
        args.append("mute" if mudo else "unmute")
    rc, _, err = _texto(["amixer", "-q", "-c", str(p["indice"]), "sset", controle] + args, 10)
    if rc != 0:
        return {"ok": False, "erro": f"Não ajustou: {err[:120]}"}
    estado = "mudo" if mudo else (f"{volume}%" if volume is not None else "ligado")
    return {"ok": True, "aviso": f"{controle}: {estado}."}


def gerar_asound(placa_id):
    if not placa_id:
        return None
    return ("# GERADO pelo OpenDongle a partir de /etc/opendongle/config.json\n"
            f'pcm.!default {{\n  type plug\n  slave.pcm "hw:{placa_id}"\n}}\n'
            f"ctl.!default {{\n  type hw\n  card {placa_id}\n}}\n")


# Melodia curta (dó-mi-sol-dó) em vez de um bipe: dá pra reconhecer como som de
# verdade, e confirma de ouvido que não é chiado nem interferência.
MELODIA = ((523.25, 0.28), (659.25, 0.28), (783.99, 0.28), (1046.50, 0.55))


def _tom(taxa=48000, notas=MELODIA, volume=11000):
    dados = bytearray()
    for freq, segundos in notas:
        n = int(segundos * taxa)
        rampa = int(0.012 * taxa)   # sobe e desce o volume: sem isso, estala
        for i in range(n):
            ganho = min(1.0, i / rampa, (n - i) / rampa)
            # 2ª harmônica baixinha deixa o timbre menos "bipe de micro-ondas"
            onda = (math.sin(2 * math.pi * freq * i / taxa)
                    + 0.22 * math.sin(4 * math.pi * freq * i / taxa)) / 1.22
            dados += struct.pack("<h", int(volume * ganho * onda))
    return bytes(dados)


def _pico(dados):
    if len(dados) < 4:
        return 0
    amostras = struct.unpack(f"<{len(dados) // 2}h", dados[:len(dados) // 2 * 2])
    return round(100 * max(abs(a) for a in amostras) / 32767)


def testar_saida(placa_id):
    p = _placa_por_id(placa_id)
    if not p:
        return {"ok": False, "erro": "Placa de som não encontrada."}
    rc, _, err = _run(["aplay", "-q", "-D", _dispositivo_alsa(p["indice"]), "-f", "S16_LE",
                       "-r", "48000", "-c", "1", "-t", "raw"], 10, _tom())
    if rc != 0:
        return {"ok": False, "erro": f"Não tocou: {err[:120]}"}
    return {"ok": True, "aviso": "Tocou o som de teste (4 notas). Ouviu?"}


def testar_entrada(placa_id):
    p = _placa_por_id(placa_id)
    if not p:
        return {"ok": False, "erro": "Placa de som não encontrada."}
    rc, dados, err = _run(["arecord", "-q", "-D", _dispositivo_alsa(p["indice"], captura=True),
                           "-f", "S16_LE", "-r", "16000", "-c", "1", "-d", "3", "-t", "raw"], 10)
    if rc != 0:
        return {"ok": False, "erro": f"Não gravou (a placa tem microfone?): {err[:100]}"}
    pico = _pico(dados)
    return {"ok": True, "aviso": f"Nível máximo do microfone em 3 s: {pico}%"
            + (" — está captando." if pico >= 5 else " — quase nada: fale perto ou confira o volume de entrada.")}


# --------------------------------------------------------------- Bluetooth (PipeWire)
def _como_usuario(cmd, timeout=15, entrada=None):
    env = ["env", f"XDG_RUNTIME_DIR=/run/user/{UID}",
           f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{UID}/bus"]
    return _run(["runuser", "-u", _usuario().pw_name, "--"] + env + cmd, timeout, entrada)


def bt_instalado():
    return all(os.path.exists(b) for b in ("/usr/bin/pipewire", "/usr/bin/wireplumber", "/usr/bin/wpctl"))


def bt_ativo():
    rc, _, _ = _como_usuario(["systemctl", "--user", "is-active", "--quiet", "wireplumber.service"], 10)
    return rc == 0


def aplicar_bt(ligar):
    """Liga/desliga PipeWire+WirePlumber do usuário. Levanta RuntimeError."""
    mudou = []
    if ligar:
        if not bt_instalado():
            raise RuntimeError("PipeWire não está instalado.")
        wp_conf = os.path.join(_usuario().pw_dir, WP_CONF_REL)
        os.makedirs(os.path.dirname(wp_conf), exist_ok=True)
        atual = open(wp_conf).read() if os.path.exists(wp_conf) else ""
        if atual != WP_CONF_CONTEUDO:
            with open(wp_conf, "w") as f:
                f.write(WP_CONF_CONTEUDO)
            _run(["chown", "-R", f"{UID}:{_usuario().pw_gid}",
                  os.path.join(_usuario().pw_dir, ".config/wireplumber")])
            mudou.append("wireplumber.conf")
        _run(["loginctl", "enable-linger", str(UID)], 15)
        for _ in range(20):   # o user@1000 sobe com o linger
            if os.path.exists(f"/run/user/{UID}/bus"):
                break
            time.sleep(0.5)
        if mudou or not bt_ativo():
            _como_usuario(["systemctl", "--user", "enable"] + SERVICOS_USUARIO, 30)
            rc, _, err = _como_usuario(["systemctl", "--user", "restart", "pipewire.service",
                                        "wireplumber.service"], 40)
            if rc != 0:
                raise RuntimeError(f"PipeWire não subiu: {err[:160]}")
            mudou.append("ligou áudio bluetooth")
        return mudou
    # o pacote do Debian habilita o PipeWire pra TODO usuário (global): sem isto
    # ele sobe em qualquer login SSH, mesmo "desligado" (visto ao vivo, com o
    # filter-chain junto). Ligado, ele fica habilitado só pro usuário do dongle.
    rc, out, _ = _texto(["systemctl", "--global", "is-enabled"] + SERVICOS_GLOBAIS, 10)
    if "enabled" in out.split():
        _run(["systemctl", "--global", "disable"] + SERVICOS_GLOBAIS, 30)
        mudou.append("pipewire global desabilitado")
    if os.path.exists(f"/run/user/{UID}/bus"):
        if bt_ativo():
            mudou.append("desligou áudio bluetooth")
        _como_usuario(["systemctl", "--user", "disable", "--now"] + SERVICOS_GLOBAIS, 30)
    rc, out, _ = _texto(["loginctl", "show-user", str(UID), "-p", "Linger", "--value"], 10)
    if out == "yes":
        _run(["loginctl", "disable-linger", str(UID)], 15)
    return mudou


def _wpctl_status():
    rc, out, _ = _como_usuario(["wpctl", "status"], 10)
    return out.decode(errors="replace") if rc == 0 else ""


def bt_aparelhos():
    """Saídas e entradas do PipeWire (wpctl status), com padrão e volume."""
    texto = _wpctl_status()
    saidas, entradas, secao = [], [], None
    em_audio = False
    for linha in texto.splitlines():
        limpa = linha.replace("│", " ").replace("├─", " ").replace("└─", " ").strip()
        if limpa.startswith("Audio"):
            em_audio = True
        elif limpa.startswith(("Video", "Settings")):
            em_audio = False
        if not em_audio:
            continue
        if limpa.startswith("Sinks:"):
            secao = saidas
            continue
        if limpa.startswith("Sources:"):
            secao = entradas
            continue
        if limpa.endswith(":"):
            secao = None
            continue
        m = re.match(r"^(\*)?\s*(\d+)\.\s+(.+?)\s+\[vol:\s*([\d.]+)(\s+MUTED)?\]", limpa)
        if m and secao is not None:
            secao.append({"id": int(m.group(2)), "nome": m.group(3), "padrao": bool(m.group(1)),
                          "volume": round(float(m.group(4)) * 100), "mudo": bool(m.group(5))})
    # o PipeWire enxerga todas as placas (a Loopback do diagnóstico, placas
    # USB que já têm cartão próprio): aqui só entra o que vem do Bluetooth
    bt = lambda x: 'api.bluez5' in _como_usuario(["wpctl", "inspect", str(x["id"])], 10)[1].decode(errors="replace")
    return {"ok": True, "saidas": [x for x in saidas if bt(x)],
            "entradas": [x for x in entradas if bt(x)]}


# Um fone Bluetooth só expõe microfone no perfil de chamada (HFP/HSP); no de
# música (A2DP) ele é só saída, com som melhor. Quem decide é o usuário.
MODOS_BT = {"musica": ("a2dp-sink", "Música (som melhor, sem microfone)"),
            "chamada": ("headset-head-unit", "Chamada (com microfone, som pior)")}


def bt_dispositivos(entradas=None):
    """Aparelhos Bluetooth do PipeWire com os perfis de música e de chamada.
    'entradas' evita repetir o wpctl quando quem chama já tem a lista."""
    rc, out, _ = _como_usuario(["pw-dump"], 25)
    try:
        dados = json.loads(out.decode(errors="replace"))
    except (ValueError, AttributeError):
        return []
    lista = []
    for o in dados:
        info = o.get("info") or {}
        props = info.get("props") or {}
        if not str(o.get("type", "")).endswith("Device") or props.get("device.api") != "bluez5":
            continue
        params = info.get("params") or {}
        perfis = {}
        for p in params.get("EnumProfile", []):
            for modo, (prefixo, _) in MODOS_BT.items():
                # "a2dp-sink" e "a2dp-sink-sbc_xq" servem: fica o primeiro
                if str(p.get("name", "")).startswith(prefixo) and modo not in perfis:
                    perfis[modo] = p.get("index")
        lista.append({"id": o["id"], "nome": props.get("device.description") or "Aparelho",
                      "perfis": perfis, "modo": ""})
    # o "Profile" que o pw-dump devolve fica desatualizado (já visto dizendo
    # "headset" com o aparelho em A2DP): o modo real é o que existe de nó —
    # com microfone (Audio/Source) é chamada, só saída é música
    # O nó do microfone continua registrado no pw-dump mesmo em modo música
    # (visto ao vivo), então quem diz a verdade é a lista de entradas ativas.
    if entradas is None:
        entradas = bt_aparelhos()["entradas"]
    com_microfone = {e["nome"] for e in entradas}
    for d in lista:
        d["modo"] = "chamada" if d["nome"] in com_microfone else "musica"
    return lista


def bt_modo_set(dev_id, modo):
    """Troca entre música e chamada. Reconecta o áudio: leva 1 a 2 segundos."""
    if modo not in MODOS_BT:
        return {"ok": False, "erro": "Modo inválido."}
    try:
        dev_id = int(dev_id)
    except (TypeError, ValueError):
        return {"ok": False, "erro": "Aparelho inválido."}
    ap = next((x for x in bt_dispositivos() if x["id"] == dev_id), None)
    if not ap:
        return {"ok": False, "erro": "Aparelho de áudio não encontrado."}
    indice = ap["perfis"].get(modo)
    if indice is None:
        return {"ok": False, "erro": f"{ap['nome']} não tem modo de "
                                     f"{'chamada' if modo == 'chamada' else 'música'}."}
    rc, _, err = _como_usuario(["wpctl", "set-profile", str(dev_id), str(indice)], 15)
    if rc != 0:
        return {"ok": False, "erro": f"Não trocou o modo: {err[:120]}"}
    time.sleep(2)   # o PipeWire refaz os nós do aparelho
    return {"ok": True, "aviso": f"{ap['nome']} em modo de "
            + ("chamada: o microfone aparece e o som fica pior." if modo == "chamada"
               else "música: som melhor, sem microfone.")}


def _no_valido(no_id):
    try:
        no_id = int(no_id)
    except (TypeError, ValueError):
        return None
    lista = bt_aparelhos()
    return no_id if any(x["id"] == no_id for x in lista["saidas"] + lista["entradas"]) else None


def bt_ajustar(no_id, volume=None, mudo=None, padrao=False):
    no_id = _no_valido(no_id)
    if no_id is None:
        return {"ok": False, "erro": "Aparelho de áudio não encontrado."}
    if padrao:
        _como_usuario(["wpctl", "set-default", str(no_id)], 10)
    if volume is not None:
        try:
            volume = max(0, min(150, int(volume)))
        except (TypeError, ValueError):
            return {"ok": False, "erro": "Volume inválido."}
        _como_usuario(["wpctl", "set-volume", str(no_id), f"{volume / 100:.2f}"], 10)
    if mudo is not None:
        _como_usuario(["wpctl", "set-mute", str(no_id), "1" if mudo else "0"], 10)
    return {"ok": True, "aviso": "Áudio ajustado."}


def bt_testar_saida(no_id):
    no_id = _no_valido(no_id)
    if no_id is None:
        return {"ok": False, "erro": "Aparelho de áudio não encontrado."}
    # --raw: sem isso o pw-cat tenta ler o stdin pela libsndfile e recusa
    # ("Format not recognised"), porque mandamos amostras cruas
    rc, _, err = _como_usuario(["pw-cat", "--playback", "--raw", "--target", str(no_id),
                                "--format", "s16", "--rate", "48000", "--channels", "1", "-"],
                               12, _tom())
    if rc != 0:
        return {"ok": False, "erro": f"Não tocou: {err[:120]}"}
    return {"ok": True, "aviso": "Tocou o som de teste (4 notas) no aparelho. Ouviu?"}


def bt_testar_entrada(no_id):
    no_id = _no_valido(no_id)
    if no_id is None:
        return {"ok": False, "erro": "Aparelho de áudio não encontrado."}
    rc, dados, err = _como_usuario(["timeout", "3", "pw-cat", "--record", "--raw", "--target",
                                    str(no_id), "--format", "s16", "--rate", "16000",
                                    "--channels", "1", "-"], 10)
    if not dados:
        return {"ok": False, "erro": f"Não gravou: {err[:120]}"}
    pico = _pico(dados)
    return {"ok": True, "aviso": f"Nível máximo do microfone em 3 s: {pico}%"
            + (" — está captando." if pico >= 5
               else " — quase nada: fale perto ou confira o volume de entrada.")}
