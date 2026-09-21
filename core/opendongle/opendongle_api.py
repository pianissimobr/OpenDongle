#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongle_api.py — a API JSON que alimenta o painel React (front-end estático)
================================================================================
O painel novo é um bundle estático (Next.js exportado) servido pelo dongle. Ele
NÃO renderiza HTML no servidor: pede os dados aqui, em JSON, e desenha no
navegador. Este módulo é só a tradução do motor (opendongle_engine e amigos)
para as formas que o front-end espera — as mesmas que antes vinham do mock em
lib/panel/store.tsx.

Regras:
  - as chaves saem em camelCase, porque é o que as telas já leem (ramMb, etc.);
  - cada domínio é embrulhado em try/except: uma falha no Bluetooth não pode
    apagar a tela inteira — o campo volta vazio e o resto aparece;
  - só LEITURA aqui. As ações (POST) continuam no motor, via executar().
"""
import os
import time

import opendongle_engine as eng
import opendongle_config as conf
import opendongle_sistema as sis
import opendongle_bluetooth as bt
import opendongle_audio as aud

REVERSAO = "/etc/opendongle/reversao.json"


def _seguro(fn, padrao):
    try:
        return fn()
    except Exception:
        return padrao


# --------------------------------------------------------------- ESTADO
def _recomendacao(st, primeiro_uso, rede_pendente):
    """A dica contextual da tela inicial. Espelha o que o motor já sabe."""
    if primeiro_uso:
        return {"id": "primeiro_uso", "severity": "info",
                "title": "Concluir a configuração inicial",
                "description": "Crie as suas senhas e o seu usuário para proteger o dongle.",
                "primary": {"label": "Continuar", "route": "/perfil"}, "secondary": []}
    if rede_pendente:
        return {"id": "confirmar_rede", "severity": "warning",
                "title": "Confirme a mudança de rede",
                "description": "Você mudou a rede há pouco. Confirme que ainda "
                               "consegue abrir o painel, senão ele será desfeito.",
                "primary": {"label": "Confirmar agora", "route": "/confirmar"}, "secondary": []}
    if not st.get("internet"):
        if st.get("modo") == "wifi":
            return {"id": "sem_internet_wifi", "severity": "warning", "title": "Sem internet",
                    "description": "O dongle está no Wi-Fi mas não sai para a internet.",
                    "primary": {"label": "Verificar conexão", "route": "/wifi"},
                    "secondary": [{"label": "Voltar ao hotspot", "route": "/hotspot"}]}
        return {"id": "hotspot_sem_saida", "severity": "info",
                "title": "O hotspot está funcionando, mas sem internet",
                "description": "Conecte um Wi-Fi ou verifique o chip 4G para ter saída.",
                "primary": {"label": "Configurar internet", "route": "/internet"}, "secondary": []}
    return None


def estado(primeiro_uso=False):
    st = _seguro(eng.status, {"modo": "indefinido", "internet": False,
                              "hotspot_ssid": None, "endereco": None})
    end = st.get("endereco")
    primeiro = bool(primeiro_uso)
    pendente = os.path.exists(REVERSAO)
    tarefa = _seguro(lambda: sis.tarefa_estado().get("nome") if sis.tarefa_estado().get("rodando") else None, None)
    return {
        "rotulo": "",
        "modo": st.get("modo", "indefinido"),
        "internet": bool(st.get("internet")),
        "ssidHotspot": st.get("hotspot_ssid"),
        "endereco": ({"ssid": end["ssid"], "ip": end["ip"], "agora": end["agora"]}
                     if end else None),
        "primeiroUso": primeiro,
        "redePendente": pendente,
        "tarefa": tarefa,
        "recomendacao": _recomendacao(st, primeiro, pendente),
    }


# --------------------------------------------------------------- SAÚDE
def saude():
    sa = _seguro(eng.saude_sistema, {})
    ram = sa.get("ram", {})
    total = ram.get("total_kb") or 1
    disp = ram.get("disponivel_kb", 0)
    temp = sa.get("temp_cpu_c")
    return {
        "ramPct": round(100 - disp * 100 / total) if total else 0,
        "tempC": round(temp) if temp is not None else 0,
        "discoPct": _seguro(lambda: sa["disco_raiz"]["usado_pct"], 0),
    }


# --------------------------------------------------------------- DADOS (MockData)
def _bluetooth():
    e = bt.estado()
    if not e.get("ok"):
        return {"ligado": False, "visivel": False, "nome": "", "mac": "",
                "buscando": False, "pareados": [], "novos": [], "erro": e.get("erro", "")}
    def dev(a):
        return {"mac": a["mac"], "nome": a["nome"], "tipo": a.get("tipo", ""),
                "conectado": a.get("conectado", False), "audio": a.get("audio", False),
                "bateria": a.get("bateria")}
    ap = e.get("aparelhos", [])
    return {
        "ligado": e.get("ligado", False), "visivel": e.get("visivel", False),
        "nome": e.get("nome", ""), "mac": e.get("mac", ""),
        "buscando": e.get("buscando", False),
        "pareados": [dev(a) for a in ap if a.get("pareado")],
        "novos": [dev(a) for a in ap if not a.get("pareado")],
    }


def _usb():
    u = sis.usb_dispositivos()
    if not u.get("ok"):
        return {"papel": "device", "aparelhos": []}
    papel = "host" if u.get("papel", "").startswith("host") else "device"
    return {"papel": papel,
            "aparelhos": [{"tipo": a.get("tipo", ""), "nome": a.get("nome", ""),
                           "id": a.get("id", "")} for a in u.get("aparelhos", [])]}


def _audio():
    ligado = _seguro(aud.bt_ativo, False)
    placas = []
    p = _seguro(aud.placas, {"ok": False})
    if p.get("ok"):
        padrao = p.get("padrao")
        for pl in p.get("placas", []):
            placas.append({
                "id": pl.get("id", ""), "nome": pl.get("nome", ""),
                "usb": pl.get("usb", False), "padrao": pl.get("id") == padrao,
                "controles": [{"nome": c.get("nome", ""), "tipo": c.get("tipo", "saída"),
                               "volume": c.get("volume", 0), "mudo": c.get("mudo", False)}
                              for c in pl.get("controles", [])],
            })
    saidas = entradas = []
    modos = {}
    if ligado:
        d = _seguro(aud.bt_dispositivos, {"ok": False})
        if d.get("ok"):
            saidas = d.get("saidas", [])
            entradas = d.get("entradas", [])
            for x in saidas + entradas:
                if x.get("modo"):
                    modos[str(x["id"])] = x["modo"]
    return {"bluetoothLigado": ligado, "placas": placas,
            "btSaidas": saidas, "btEntradas": entradas, "btModos": modos}


def _modem():
    m = _seguro(eng.modem_status, {"presente": False})
    if not m.get("presente"):
        return {"presente": False, "simPresente": False, "registrado": False,
                "operadora": "", "rssiDbm": 0, "modoOperacao": "", "imei": "",
                "firmwareOk": True, "diagnostico": ""}
    fw = m.get("firmware_ok")
    return {"presente": True, "simPresente": m.get("sim_presente", False),
            "registrado": m.get("registrado", False), "operadora": m.get("operadora", ""),
            "rssiDbm": m.get("rssi_dbm") or 0, "modoOperacao": m.get("modo_operacao", ""),
            "imei": m.get("imei", ""), "mccMnc": m.get("mcc_mnc", ""),
            "firmwareOk": fw is not False, "diagnostico": m.get("diagnostico", "")}


def _lan():
    cfg = _seguro(lambda: conf.carregar(), conf.PADRAO)
    lan = cfg["lan"]
    dhcp = lan["dhcp"]
    clientes = _seguro(lambda: eng.dhcp_clientes().get("clientes", []), [])
    return {"ip": lan["ip"], "prefixo": lan["prefixo"],
            "dhcpInicio": dhcp["inicio"], "dhcpFim": dhcp["fim"], "lease": dhcp["lease"],
            "clientes": [{"mac": c["mac"], "ip": c["ip"], "nome": c.get("nome", ""),
                          "fixo": c.get("fixo", False)} for c in clientes],
            "fixos": [{"mac": f["mac"], "ip": f["ip"], "nome": f.get("nome", "")}
                      for f in dhcp["fixos"]]}


def _firewall():
    cfg = _seguro(lambda: conf.carregar(), conf.PADRAO)
    fw = cfg["firewall"]
    return {"wifiClienteConfiavel": fw.get("wifi_cliente_confiavel", True),
            "sshPelaWan": fw.get("ssh_pela_wan", False),
            "painelPelaWan": fw.get("painel_pela_wan", False),
            "redirecionamentos": [{"nome": r["nome"], "proto": r["proto"],
                                   "portaExterna": r["porta_externa"], "ip": r["ip"],
                                   "portaInterna": r["porta_interna"]}
                                  for r in fw.get("redirecionamentos", [])]}


def _servicos():
    r = _seguro(sis.servicos, {"ok": False})
    if not r.get("ok"):
        return []
    return [{"nome": s["nome"], "habilitado": s["habilitado"], "rodando": s["rodando"],
             "ramMb": s.get("ram_mb", 0), "essencial": s.get("essencial", False),
             "gerenciado": s.get("gerenciado", ""), "gerenciadoUrl": s.get("gerenciado_url", ""),
             "aviso": s.get("aviso", "")} for s in r.get("servicos", [])]


def dados():
    cfg = _seguro(lambda: conf.carregar(), conf.PADRAO)
    return {
        "bluetooth": _seguro(_bluetooth, {"ligado": False, "visivel": False, "nome": "",
                                          "mac": "", "buscando": False, "pareados": [], "novos": []}),
        "usb": _seguro(_usb, {"papel": "device", "aparelhos": []}),
        "audio": _seguro(_audio, {"bluetoothLigado": False, "placas": [],
                                  "btSaidas": [], "btEntradas": [], "btModos": {}}),
        "modem": _seguro(_modem, {"presente": False}),
        "lan": _seguro(_lan, {}),
        "firewall": _seguro(_firewall, {}),
        "leds": cfg["sistema"]["leds"],
        "hostname": cfg["sistema"]["hostname"],
        "servicos": _seguro(_servicos, []),
        "tor": {"ativo": cfg["tor"]["ativo"]},
        "remoto": {"ativo": cfg["remoto"]["ativo"], "lan": cfg["remoto"]["lan"],
                   "saida": cfg["remoto"]["saida"]},
        "hora": _seguro(lambda: {"automatica": cfg["sistema"]["hora_automatica"],
                                 "fuso": cfg["sistema"]["fuso"],
                                 "agora": sis.hora_status().get("agora", "")}, {}),
    }


def wifi_scan():
    """Redes Wi-Fi ao alcance. Lento (~alguns segundos): o front pede quando
    a pessoa abre a tela de conectar."""
    r = _seguro(eng.listar_wifi, {"ok": False})
    redes = [{"ssid": x.get("ssid", ""), "sinal": x.get("sinal", 0),
              "seguranca": x.get("seg", "")} for x in r.get("redes", []) if x.get("ssid")]
    return {"ok": r.get("ok", False), "redes": redes, "aviso": r.get("aviso", "")}


def perfil():
    return {"nome": _seguro(eng.nome_completo, "") or _seguro(eng.admin_usuario, "admin"),
            "usuario": _seguro(eng.admin_usuario, "admin"), "admin": True,
            "foto": _seguro(eng.avatar_tem, False)}


def tudo(primeiro_uso=False):
    """Um pedido só, quando o front quer o estado completo (menos requisições
    = menos idas ao dongle, que dorme por RAM)."""
    return {"estado": estado(primeiro_uso), "saude": saude(),
            "dados": dados(), "perfil": perfil()}


# =============================================================== AÇÕES (POST)
# Despacho nome->função real. O que não estiver aqui cai em eng.executar, que
# já cobre o dicionário ACOES do motor (config, backup, wifi-auto, rede-*, ...).
# As formas dos args são as que o front-end envia (ver lib/panel/store).
_ACOES = {
    # --- rede local / firewall ---
    "lan-set": lambda a: eng.lan_set(a["ip"], a.get("prefixo", 24),
                                     a["inicio"], a["fim"], a.get("lease", "12h")),
    "fixo-add": lambda a: eng.dhcp_fixo_add(a["mac"], a["ip"], a.get("nome", "")),
    "fixo-rm": lambda a: eng.dhcp_fixo_rm(a["mac"]),
    "fw-set": lambda a: eng.fw_set(bool(a.get("wifiClienteConfiavel", True)),
                                   bool(a.get("sshPelaWan", False)),
                                   bool(a.get("painelPelaWan", False))),
    "redir-add": lambda a: eng.fw_redir_add(a["nome"], a["proto"], a["portaExterna"],
                                            a["ip"], a["portaInterna"]),
    "redir-rm": lambda a: eng.fw_redir_rm(a["nome"]),
    # --- modem 4G ---
    "modem-apn": lambda a: eng.modem_apn_auto(a["apn"]),
    "modem-reconectar": lambda a: eng.modem_reconectar(),
    # --- privacidade / acesso remoto ---
    "tor-set": lambda a: eng.tor_set(bool(a.get("ligar"))),
    "remoto-set": lambda a: eng.remoto_set(bool(a.get("ligar")), bool(a.get("lan")),
                                           bool(a.get("saida"))),
    # --- sistema ---
    "led-set": lambda a: eng.led_set(a["led"], a["gatilho"]),
    "hora-set": lambda a: eng.hora_set(bool(a.get("automatica", True)), a.get("fuso", "")),
    "hora-manual": lambda a: sis.hora_manual(a["data"], a["hora"]),
    "sistema-set": lambda a: eng.sistema_set(a.get("hostname", "")),
    "servico-set": lambda a: sis.servico_set(a["nome"], bool(a.get("ligar"))),
    "energia": lambda a: sis.energia(a["acao"]),
    "processo-encerrar": lambda a: sis.encerrar_processo(a["pid"]),
    "espaco-analisar": lambda a: sis.espaco_analisar(),
    "espaco-liberar": lambda a: sis.espaco_liberar(),
    "atualizacoes": lambda a: sis.atualizacoes_iniciar(bool(a.get("instalar"))),
    "sessao-encerrar": lambda a: sis.encerrar_sessao(a["id"]),
    # --- USB ---
    "usb-papel": lambda a: sis.usb_papel(a["papel"]),
    # --- Bluetooth ---
    "bt-ligar": lambda a: bt.ligar(bool(a.get("ligar", True))),
    "bt-visivel": lambda a: bt.visivel(bool(a.get("visivel", True))),
    "bt-buscar": lambda a: bt.buscar(),
    "bt-conectar": lambda a: bt.conectar(a["mac"]),
    "bt-desconectar": lambda a: bt.desconectar(a["mac"]),
    "bt-esquecer": lambda a: bt.esquecer(a["mac"]),
    "bt-parear": lambda a: bt.parear(a["mac"]),
    "bt-responder": lambda a: bt.responder(a.get("valor")),
    "bt-renomear": lambda a: bt.renomear(a["nome"]),
    # --- Áudio ---
    "audio-bt-set": lambda a: eng.audio_bt_set(bool(a.get("ligar"))),
    "audio-ajustar": lambda a: aud.ajustar(a["placa"], a["controle"],
                                           a.get("volume"), a.get("mudo")),
    "audio-padrao": lambda a: eng.audio_placa_padrao(a["placa"]),
    "audio-testar": lambda a: aud.testar_saida(a["placa"]),
    "audio-bt-modo": lambda a: aud.bt_modo_set(a["dev"], a["modo"]),
    "audio-bt-ajustar": lambda a: aud.bt_ajustar(a["no"], a.get("volume"),
                                                 a.get("mudo"), bool(a.get("padrao"))),
}


def acao(nome, args):
    """Executa uma ação e devolve {ok, ...} do motor. Nomes fora do mapa caem
    em eng.executar (as ações do dicionário ACOES). set-password e renomear
    NÃO passam por aqui: a casca web trata (revalida a senha atual)."""
    args = args or {}
    fn = _ACOES.get(nome)
    try:
        return fn(args) if fn else eng.executar(nome, args)
    except KeyError as e:
        return {"ok": False, "erro": f"faltou o campo {e} na ação {nome}."}
    except Exception as e:
        return {"ok": False, "erro": str(e)}
