#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongle_bluetooth.py — Bluetooth completo com bluetoothd sob demanda
=========================================================================
Usado pelo painel e pela CLI. Sem python3-dbus: fala com o BlueZ pelo
bluetoothctl. O pareamento com PIN/confirmação de código precisa de um
"agent" interativo, então roda o bluetoothctl num pseudo-terminal (pty) e
responde às perguntas dele com o que o usuário digitou no painel.

bluetoothd sob demanda: fica habilitado (e reconecta teclado/fone no boot)
só se houver aparelho pareado. Sem nenhum, sobe quando o painel usa o
Bluetooth e para quando o painel dorme (reconciliar).

Busca e pareamento rodam como unit temporária com o estado em /run: o
painel pode dormir e a página só lê o arquivo.
"""

import glob
import json
import os
import pty
import re
import select
import subprocess
import sys
import time

RUN = "/run/opendongle"
PAREAR_JSON = f"{RUN}/bt-pareamento.json"
RESPOSTA = f"{RUN}/bt-resposta"
UNIT_BUSCA = "opendongle-bt-busca"
UNIT_PAREAR = "opendongle-bt-parear"
SVC = "bluetooth.service"
TEMPO_BUSCA = 20
ESPERA_RESPOSTA = 60

RE_MAC = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")
RE_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x01|\x02")
RE_NOME = re.compile(r"^[A-Za-z0-9 ._\-]{1,32}$")
# Icon do BlueZ -> (emoji, tipo)
TIPOS = {"audio-headset": ("🎧", "Fone"), "audio-headphones": ("🎧", "Fone"),
         "audio-card": ("🔊", "Caixa de som"), "input-keyboard": ("⌨️", "Teclado"),
         "input-mouse": ("🖱️", "Mouse"), "input-gaming": ("🎮", "Controle"),
         "input-tablet": ("✏️", "Mesa digitalizadora"), "phone": ("📱", "Celular"),
         "computer": ("💻", "Computador"), "printer": ("🖨️", "Impressora"),
         "camera-photo": ("📷", "Câmera"), "camera-video": ("📹", "Câmera")}


# Erros do BlueZ em português, com o que fazer. A ordem importa: o primeiro
# trecho que casar decide a mensagem.
ERROS_BLUEZ = [
    ("br-connection-profile-unavailable",
     "O dongle não tem o serviço que esse aparelho usa. Se for fone ou caixa de som, "
     "ligue o áudio Bluetooth na categoria Áudio e tente de novo."),
    ("profile-unavailable", "O dongle não tem o serviço que esse aparelho usa."),
    ("AuthenticationRejected", "O aparelho recusou o pareamento. Coloque-o em modo de "
                               "pareamento e tente de novo."),
    ("AuthenticationFailed", "Código não confere ou foi recusado no aparelho."),
    ("AuthenticationCanceled", "O pareamento foi cancelado no aparelho."),
    ("AuthenticationTimeout", "O aparelho não respondeu a tempo."),
    ("ConnectionAttemptFailed", "O aparelho não respondeu. Deixe-o ligado e por perto."),
    ("Page Timeout", "O aparelho não respondeu. Deixe-o ligado e por perto."),
    ("Host is down", "O aparelho está desligado ou fora de alcance."),
    ("AlreadyExists", "Este aparelho já está pareado."),
    ("InProgress", "Já tem uma operação de Bluetooth em andamento. Espere alguns segundos."),
    ("not available", "Aparelho fora de alcance. Procure de novo com ele em modo de pareamento."),
    ("NotConnected", "O aparelho não está conectado."),
]


def _traduz(detalhe):
    for trecho, texto in ERROS_BLUEZ:
        if trecho in detalhe:
            return texto
    return detalhe


# Perfis de som (A2DP sink/source, AVRCP, mãos-livres e fone). Um aparelho que
# anuncia qualquer um deles só conecta com o PipeWire do usuário no ar.
UUIDS_AUDIO = ("0000110a", "0000110b", "0000110c", "0000110d", "0000110e",
               "00001108", "0000111e", "0000111f")


def eh_audio(mac, info=None):
    """O aparelho toca ou capta som? Pelo ícone do BlueZ, pela classe ou pelos
    perfis anunciados (o ícone falta em vários fones baratos)."""
    if info is None:
        _, info, _ = _ctl("info", mac, timeout=6)
    c = _campos(info)
    if c.get("Icon", "").startswith("audio"):
        return True
    if any(u in info.lower() for u in UUIDS_AUDIO):
        return True
    classe = re.search(r"Class: 0x([0-9a-fA-F]+)", info)
    if classe:   # classe "major device": 0x04 = áudio/vídeo
        return (int(classe.group(1), 16) >> 8) & 0x1f == 0x04
    return False


def _audio():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import opendongle_audio as aud
    return aud


def preparar_audio(mac, info=None):
    """Antes de conectar um fone ou caixa: sobe o áudio Bluetooth (PipeWire)
    sozinho, porque sem ele o BlueZ não tem perfil de som e recusa a conexão.
    Devolve (pronto, motivo): motivo "instalar" quando falta baixar o PipeWire."""
    try:
        if not eh_audio(mac, info):
            return True, ""
        aud = _audio()
        if aud.bt_ativo():
            return True, ""
        if not aud.bt_instalado():
            return False, "instalar"
        import opendongle_engine as eng   # grava na config e aplica, como a tela de Áudio
        r = eng.audio_bt_set(True)
        return bool(r.get("ok")), "" if r.get("ok") else r.get("erro", "")
    except Exception as e:
        return False, f"não consegui ligar o áudio Bluetooth: {e}"


def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, RE_ANSI.sub("", r.stdout).strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", "bluez não instalado"


def _ativo(unit):
    return _run(["systemctl", "is-active", "--quiet", unit], 10)[0] == 0


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


def _garantir_bluetoothd():
    """Sobe o bluetoothd se estiver parado. Com o serviço desabilitado a
    ativação por D-Bus não funciona (bluetoothctl ficaria esperando pra
    sempre), por isso o start explícito."""
    if _ativo(SVC):
        return True
    _run(["rfkill", "unblock", "bluetooth"], 5)
    _run(["systemctl", "start", SVC], 30)
    for _ in range(20):
        rc, show, _ = _run(["bluetoothctl", "show"], 5)
        if rc == 0:
            # sem nome escolhido o BlueZ se anuncia como "BlueZ 5.82": usa o
            # nome do dongle (o mesmo do opendongle.local)
            if _campos(show).get("Alias", "").startswith("BlueZ"):
                _run(["bluetoothctl", "system-alias", os.uname().nodename[:32]], 5)
            return True
        time.sleep(0.5)
    return False


def _ctl(*args, timeout=15):
    # sem --timeout: com ele o bluetoothctl espera o prazo inteiro antes de
    # sair até num "show" (medido: 6,09 s contra 0,19 s). O limite fica no
    # subprocess; só o "scan" usa --timeout (ali ele define a duração).
    return _run(["bluetoothctl"] + list(args), timeout)


def _campos(texto):
    """'Chave: valor' do bluetoothctl show/info (a primeira ocorrência vale)."""
    campos = {}
    for linha in texto.splitlines():
        chave, sep, valor = linha.strip().partition(": ")
        if sep and chave not in campos:
            campos[chave] = valor.strip()
    return campos


def _mac_valido(mac):
    mac = (mac or "").strip().upper()
    return mac if RE_MAC.match(mac) else None


# --------------------------------------------------------------- leitura barata
def resumo():
    """Ligado/pareados SEM subir o bluetoothd: kernel (sysfs) + /var/lib/bluetooth."""
    ligado = False
    for r in glob.glob("/sys/class/rfkill/rfkill*"):
        try:
            if open(f"{r}/type").read().strip() == "bluetooth":
                ligado = open(f"{r}/soft").read().strip() == "0" and \
                    open(f"{r}/hard").read().strip() == "0"
        except OSError:
            pass
    return {"ok": True, "ligado": ligado and os.path.isdir("/sys/class/bluetooth/hci0"),
            "pareados": len(_pareados_em_disco()), "daemon": _ativo(SVC)}


def _pareados_em_disco():
    pareados = []
    for info in glob.glob("/var/lib/bluetooth/*/*/info"):
        try:
            texto = open(info).read()
        except OSError:
            continue
        if re.search(r"^\[(LinkKey|LongTermKey|PeripheralLongTermKey|SlaveLongTermKey)\]",
                     texto, re.M):
            pareados.append(os.path.basename(os.path.dirname(info)))
    return pareados


# --------------------------------------------------------------- estado completo
def estado():
    if not _garantir_bluetoothd():
        return {"ok": False, "erro": "O serviço de Bluetooth não subiu (bluez instalado?)."}
    rc, show, _ = _ctl("show", timeout=8)
    if rc != 0:
        return {"ok": False, "erro": "Nenhum adaptador Bluetooth respondeu."}
    ad = _campos(show)
    _, lista, _ = _ctl("devices", timeout=8)
    _, lista_pareados, _ = _ctl("devices", "Paired", timeout=8)
    pareados = {l.split()[1] for l in lista_pareados.splitlines() if l.startswith("Device ")}
    aparelhos, sem_nome = [], 0
    for linha in lista.splitlines():
        partes = linha.split(" ", 2)
        if len(partes) < 2 or partes[0] != "Device":
            continue
        # beacons BLE sem nome aparecem com o próprio MAC (com traços) no lugar
        # do nome: contados e descartados antes do "info" (~0,2 s cada)
        if partes[1] not in pareados and re.match(
                r"^[0-9A-F]{2}(-[0-9A-F]{2}){5}$", partes[2] if len(partes) > 2 else ""):
            sem_nome += 1
            continue
        if len(aparelhos) >= 30:
            break
        _, info, _ = _ctl("info", partes[1], timeout=6)
        c = _campos(info)
        pareado = c.get("Paired") == "yes"
        if not c.get("Name") and not pareado:
            sem_nome += 1
            continue
        emoji, tipo = TIPOS.get(c.get("Icon", ""), ("🔷", "Aparelho"))
        bateria = re.search(r"\((\d+)\)", c.get("Battery Percentage", ""))
        aparelhos.append({"mac": partes[1], "nome": c.get("Alias") or c.get("Name") or partes[1],
                          "emoji": emoji, "tipo": tipo, "pareado": pareado,
                          "conectado": c.get("Connected") == "yes",
                          "confiavel": c.get("Trusted") == "yes",
                          "bateria": int(bateria.group(1)) if bateria else None,
                          "audio": c.get("Icon", "").startswith("audio")})
    aparelhos.sort(key=lambda a: (not a["pareado"], not a["conectado"], a["nome"].lower()))
    return {"ok": True, "ligado": ad.get("Powered") == "yes",
            "visivel": ad.get("Discoverable") == "yes", "nome": ad.get("Alias", ""),
            "mac": show.split()[1] if show.startswith("Controller") else "",
            "aparelhos": aparelhos, "sem_nome": sem_nome,
            "buscando": _ativo(f"{UNIT_BUSCA}.service"),
            "pareamento": pareamento_estado()}


# --------------------------------------------------------------- ações do adaptador
def _resultado(rc, out, err, ok_msg, erro_msg):
    if rc == 0 and "Failed" not in out and "not available" not in out:
        return {"ok": True, "aviso": ok_msg}
    detalhe = next((l for l in (out + "\n" + err).splitlines()
                    if "Failed" in l or "Error" in l or "not available" in l), err or out)
    return {"ok": False, "erro": f"{erro_msg}: {_traduz(detalhe)[:200]}"}


def ligar(sim):
    if sim:
        _run(["rfkill", "unblock", "bluetooth"], 5)
    if not _garantir_bluetoothd():
        return {"ok": False, "erro": "O serviço de Bluetooth não subiu."}
    return _resultado(*_ctl("power", "on" if sim else "off"),
                      "Bluetooth ligado." if sim else "Bluetooth desligado.", "Não mudou")


def visivel(sim):
    if not _garantir_bluetoothd():
        return {"ok": False, "erro": "O serviço de Bluetooth não subiu."}
    _ctl("pairable", "on" if sim else "off")
    return _resultado(*_ctl("discoverable", "on" if sim else "off"),
                      "Visível pra outros aparelhos por 3 minutos." if sim else "Oculto.",
                      "Não mudou")


def renomear(nome):
    nome = (nome or "").strip()
    if not RE_NOME.match(nome):
        return {"ok": False, "erro": "Nome inválido (até 32 letras, números, espaço, . _ -)."}
    if not _garantir_bluetoothd():
        return {"ok": False, "erro": "O serviço de Bluetooth não subiu."}
    return _resultado(*_ctl("system-alias", nome), f"Nome Bluetooth: {nome}.", "Não renomeou")


def buscar():
    if not _garantir_bluetoothd():
        return {"ok": False, "erro": "O serviço de Bluetooth não subiu."}
    if _ativo(f"{UNIT_BUSCA}.service"):
        return {"ok": True, "aviso": "Já está procurando."}
    _run(["systemctl", "reset-failed", f"{UNIT_BUSCA}.service"], 5)
    _run(["systemd-run", f"--unit={UNIT_BUSCA}", "--collect", "bluetoothctl",
          "--timeout", str(TEMPO_BUSCA), "scan", "on"], 10)
    return {"ok": True, "aviso": f"Procurando aparelhos por {TEMPO_BUSCA} segundos. "
            "Deixe o aparelho em modo de pareamento."}


# --------------------------------------------------------------- ações por aparelho
def conectar(mac):
    mac = _mac_valido(mac)
    if not mac:
        return {"ok": False, "erro": "Endereço MAC inválido."}
    _garantir_bluetoothd()
    pronto, motivo = preparar_audio(mac)
    if not pronto and motivo == "instalar":
        # o PipeWire ainda não está no dongle: quem chama (painel) instala em
        # segundo plano, porque leva minutos
        return {"ok": False, "instalar_audio": True,
                "erro": "Este aparelho é de som e o dongle ainda precisa baixar o "
                        "programa de áudio Bluetooth."}
    r = _resultado(*_ctl("connect", mac, timeout=25), "Conectado.", "Não conectou")
    if r["ok"]:
        _ctl("trust", mac, timeout=8)   # reconecta sozinho no próximo boot
        if eh_audio(mac):
            r["aviso"] = "Conectado. Em Áudio, toque em Tocar som de teste pra ouvir."
    elif motivo:
        r["erro"] += f" ({motivo})"
    return r


def desconectar(mac):
    mac = _mac_valido(mac)
    if not mac:
        return {"ok": False, "erro": "Endereço MAC inválido."}
    _garantir_bluetoothd()
    return _resultado(*_ctl("disconnect", mac, timeout=15), "Desconectado.", "Não desconectou")


def esquecer(mac):
    mac = _mac_valido(mac)
    if not mac:
        return {"ok": False, "erro": "Endereço MAC inválido."}
    _garantir_bluetoothd()
    r = _resultado(*_ctl("remove", mac), "Aparelho esquecido.", "Não removeu")
    reconciliar()
    return r


# --------------------------------------------------------------- pareamento (pty)
def pareamento_estado():
    est = _ler_json(PAREAR_JSON)
    if est and est.get("etapa") not in ("ok", "erro") and not _ativo(f"{UNIT_PAREAR}.service"):
        est = dict(est, etapa="erro", erro="O pareamento foi interrompido.")
    return est


def parear(mac):
    mac = _mac_valido(mac)
    if not mac:
        return {"ok": False, "erro": "Endereço MAC inválido."}
    if not _garantir_bluetoothd():
        return {"ok": False, "erro": "O serviço de Bluetooth não subiu."}
    if _ativo(f"{UNIT_PAREAR}.service"):
        return {"ok": False, "erro": "Já tem um pareamento em andamento."}
    _ctl("scan", "off", timeout=5)   # busca ativa atrapalha o pareamento
    _run(["systemctl", "stop", f"{UNIT_BUSCA}.service"], 10)
    for arquivo in (RESPOSTA,):
        try:
            os.unlink(arquivo)
        except OSError:
            pass
    _gravar_json(PAREAR_JSON, {"mac": mac, "etapa": "iniciando", "quando": time.time()})
    _run(["systemctl", "reset-failed", f"{UNIT_PAREAR}.service"], 5)
    _run(["systemd-run", f"--unit={UNIT_PAREAR}", "--collect", "/usr/bin/python3",
          os.path.abspath(__file__), "parear", mac], 10)
    return {"ok": True, "aviso": "Pareando… siga as instruções na tela."}


def responder(valor):
    """sim | nao | PIN (até 16 letras/números) | passkey (até 6 dígitos)."""
    valor = (valor or "").strip()
    if not re.match(r"^(sim|nao|[A-Za-z0-9]{1,16})$", valor):
        return {"ok": False, "erro": "Resposta inválida."}
    est = pareamento_estado() or {}
    if est.get("etapa") not in ("confirmar", "pin", "passkey"):
        return {"ok": False, "erro": "Não há pergunta de pareamento esperando resposta."}
    os.makedirs(RUN, exist_ok=True)
    with open(RESPOSTA + ".tmp", "w") as f:
        f.write(valor)
    os.replace(RESPOSTA + ".tmp", RESPOSTA)
    return {"ok": True, "aviso": "Resposta enviada."}


def _trabalho_parear(mac):
    estado_atual = {"mac": mac, "etapa": "iniciando", "quando": time.time()}

    def muda(**kw):
        estado_atual.update(kw, quando=time.time())
        _gravar_json(PAREAR_JSON, estado_atual)

    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("bluetoothctl", ["bluetoothctl"])
    envia = lambda txt: os.write(fd, (txt + "\n").encode())

    def espera_resposta():
        prazo = time.time() + ESPERA_RESPOSTA
        while time.time() < prazo:
            try:
                valor = open(RESPOSTA).read().strip()
                os.unlink(RESPOSTA)
                return valor
            except OSError:
                time.sleep(0.4)
        return None

    try:
        time.sleep(1)
        for cmd in ("agent KeyboardDisplay", "default-agent", "pairable on", f"pair {mac}"):
            envia(cmd)
            time.sleep(0.3)
        buffer, prazo = "", time.time() + 90
        while time.time() < prazo:
            prontos, _, _ = select.select([fd], [], [], 1)
            if not prontos:
                continue
            try:
                pedaco = RE_ANSI.sub("", os.read(fd, 4096).decode(errors="replace"))
            except OSError:
                break
            buffer += pedaco
            # vai pro journal (unit temporária): sem isto não sobra rastro nenhum
            # de um pareamento que falhou
            sys.stderr.write(pedaco)
            sys.stderr.flush()
            m = re.search(r"Confirm passkey (\d+)", buffer)
            if m:
                buffer = ""
                muda(etapa="confirmar", codigo=m.group(1))
                r = espera_resposta()
                envia("yes" if r == "sim" else "no")
                if r != "sim":
                    muda(etapa="erro", erro="Pareamento recusado." if r else "Tempo esgotado.")
                    return
                muda(etapa="iniciando", codigo="")
                continue
            if re.search(r"Enter PIN code", buffer) or re.search(r"Enter passkey", buffer):
                etapa = "pin" if "PIN" in buffer else "passkey"
                buffer = ""
                muda(etapa=etapa)
                r = espera_resposta()
                if not r or r in ("sim", "nao"):
                    envia("")
                    muda(etapa="erro", erro="Tempo esgotado." if not r else "Pareamento cancelado.")
                    return
                envia(r)
                muda(etapa="iniciando")
                continue
            m = re.search(r"Passkey: (\d+)", buffer)
            if m:
                buffer = ""
                muda(etapa="digitar", codigo=m.group(1))
                continue
            if re.search(r"(Authorize service|Request authorization|Accept pairing).*\(yes/no\)", buffer):
                buffer = ""
                envia("yes")
                continue
            if "Pairing successful" in buffer:
                envia(f"trust {mac}")
                time.sleep(1)
                # fone/caixa: sobe o áudio Bluetooth antes de conectar
                pronto, motivo = preparar_audio(mac)
                if not pronto and motivo == "instalar":
                    try:
                        import opendongle_sistema as sis
                        sis.tarefa_iniciar("audio-bt")
                        muda(etapa="ok", codigo="",
                             aviso="Pareado. Estou baixando o programa de áudio Bluetooth "
                                   "(alguns minutos); quando terminar, toque em Conectar.")
                    except Exception as e:
                        muda(etapa="ok", codigo="", aviso=f"Pareado, mas o áudio não subiu: {e}")
                    reconciliar()
                    return
                buffer = ""
                envia(f"connect {mac}")
                fim_conexao = time.time() + 20
                while time.time() < fim_conexao and "Connection successful" not in buffer:
                    pr, _, _ = select.select([fd], [], [], 1)
                    if not pr:
                        continue
                    try:
                        pedaco = RE_ANSI.sub("", os.read(fd, 4096).decode(errors="replace"))
                    except OSError:
                        break
                    buffer += pedaco
                    sys.stderr.write(pedaco)
                    sys.stderr.flush()
                    if "Failed to connect" in buffer:
                        break
                falha_con = re.search(r"Failed to connect:?([^\n]*)", buffer)
                aviso = ""
                if falha_con:
                    aviso = _traduz(falha_con.group(1).strip())
                    if "profile" in falha_con.group(1) and _audio_bt_desligado(mac):
                        aviso = ("Ligue o áudio Bluetooth em Áudio pra usar o som deste "
                                 "aparelho, e depois toque em Conectar.")
                muda(etapa="ok", codigo="", aviso=aviso)
                reconciliar()
                return
            falha = re.search(r"(Failed to pair[^\n]*|Device [0-9A-F:]+ not available)", buffer)
            if falha:
                muda(etapa="erro", erro=_traduz(falha.group(1)))
                return
        muda(etapa="erro", erro="Tempo esgotado.")
    finally:
        try:
            envia("quit")
            time.sleep(0.5)
            os.kill(pid, 9)
            os.waitpid(pid, 0)
        except OSError:
            pass


# --------------------------------------------------------------- sob demanda
def reconciliar(parar=False):
    """Com aparelho pareado: bluetoothd habilitado (reconecta no boot).
    Sem nenhum: desabilitado; com parar=True (painel dormindo) também para,
    a não ser que haja busca ou pareamento em andamento."""
    if _pareados_em_disco():
        _run(["systemctl", "enable", "--now", SVC], 30)
        return {"ok": True, "aviso": "Há aparelhos pareados: Bluetooth sempre ligado."}
    _run(["systemctl", "disable", SVC], 30)
    ocupado = _ativo(f"{UNIT_BUSCA}.service") or _ativo(f"{UNIT_PAREAR}.service")
    if parar and not ocupado:
        _run(["systemctl", "stop", SVC], 30)
    return {"ok": True, "aviso": "Nenhum aparelho pareado: Bluetooth sob demanda."}


if __name__ == "__main__" and sys.argv[1:2] == ["parear"]:
    _trabalho_parear(sys.argv[2])
