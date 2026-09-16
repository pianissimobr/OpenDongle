#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongle_web.py — Painel web do dongle (casca sobre o motor único)
=====================================================================
Roda NO DONGLE na porta 80. Serve o onboarding e o painel de config,
chamando o MESMO opendongle_engine que a CLI usa. Só stdlib.

Fluxo de primeiro uso:
  conecta no Wi-Fi OpenDongle/opendongle → abre opendongle.local (ou IP)
  → escolhe "hotspot de internet" ou "conectar a um Wi-Fi" → vê status.

Depois de configurado, opendongle.local é o PAINEL: status, trocar
nome/senha do hotspot, alternar modo, trocar senha de admin.

Autenticação: as ações de mudança exigem login com a senha de admin
(a mesma do sistema). Leitura de status é livre na rede local.
"""

import html
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opendongle_engine as eng
import opendongle_diag as diag

IP = "192.168.100.1"
SESSOES = set()
# resultado do último diagnóstico de hardware (nome_teste -> {status,
# detalhe, quando}) — cache em memória, mesmo espírito de SESSOES: não
# precisa sobreviver a um restart do serviço.
ULTIMO_DIAG = {}
DETECCAO = ("/generate_204", "/gen_204", "/hotspot-detect.html",
            "/ncsi.txt", "/connecttest.txt", "/canonical.html")

ESTILO = """<style>
:root{--bg:#0b1220;--card:#151f36;--in:#0b1220;--br:#243050;
 --tx:#e6ecf7;--mut:#8ea0c4;--ac:#4f8cff;--ok:#34d399;--er:#f87171}
*{box-sizing:border-box}body{font-family:system-ui,sans-serif;margin:0;
 background:var(--bg);color:var(--tx);display:flex;justify-content:center;
 padding:20px}.wrap{width:100%;max-width:440px}
.card{background:var(--card);border:1px solid var(--br);border-radius:16px;
 padding:24px;margin-bottom:16px}h1{font-size:1.35em;margin:0 0 4px}
h2{font-size:1.05em;margin:0 0 12px}p{color:var(--mut);line-height:1.5}
label{display:block;font-size:.85em;color:var(--mut);margin:12px 0 4px}
input,select{width:100%;padding:12px;border-radius:10px;border:1px solid
 var(--br);background:var(--in);color:var(--tx);font-size:1em}
button{width:100%;padding:13px;margin-top:16px;border:0;border-radius:10px;
 background:var(--ac);color:#fff;font-size:1em;font-weight:600;cursor:pointer}
button.sec{background:#26324f}a.btn{display:block;text-decoration:none;
 text-align:center}.badge{display:inline-block;padding:4px 10px;border-radius:
 20px;font-size:.8em;font-weight:600}.b-ok{background:rgba(52,211,153,.15);
 color:var(--ok)}.b-er{background:rgba(248,113,113,.15);color:var(--er)}
.row{display:flex;gap:10px}.row>*{flex:1}.msg{padding:10px;border-radius:8px;
 margin-top:12px;font-size:.9em}.msg.ok{background:rgba(52,211,153,.12);
 color:var(--ok)}.msg.er{background:rgba(248,113,113,.12);color:var(--er)}
.aviso{background:rgba(251,191,36,.1);border:1px solid #a16207;border-radius:
 8px;padding:10px;font-size:.85em;color:#fcd34d;margin-top:12px}
.stats{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:12px}
.stat{background:var(--in);border:1px solid var(--br);border-radius:10px;
 padding:10px;text-align:center}
.stat span{display:block;font-size:.75em;color:var(--mut);margin-bottom:2px}
.stat b{display:block;font-size:1.3em}
.stat b.av{color:#fcd34d}.stat b.er{color:var(--er)}
.b-av{background:rgba(251,191,36,.15);color:#fcd34d}
.linha{display:flex;justify-content:space-between;align-items:center;
 text-decoration:none;color:var(--tx);padding:10px 0;border-bottom:1px
 solid var(--br)}.linha:last-child{border-bottom:none}</style>"""


def page(corpo, titulo="OpenDongle"):
    return (f"<!doctype html><html lang='pt-br'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,"
            f"initial-scale=1'><title>{titulo}</title>{ESTILO}</head>"
            f"<body><div class='wrap'>{corpo}</div></body></html>").encode()


def msg(txt, tipo="ok"):
    return f"<div class='msg {tipo}'>{html.escape(txt)}</div>" if txt else ""


# ---------- telas ----------
def _nivel(v, aviso, critico, menor_pior=False):
    """Classe CSS (''/'av'/'er') pra um valor contra dois limites. Com
    menor_pior=True, 'pior' é ir PRA BAIXO do limite (ex: RAM disponível)."""
    if v is None:
        return ""
    pior = (v <= aviso) if menor_pior else (v >= aviso)
    grave = (v <= critico) if menor_pior else (v >= critico)
    return "er" if grave else ("av" if pior else "")


def _resumo_hardware():
    bt = eng.bluetooth_status()
    bt_badge = ("<span class='badge b-ok'>ligado</span>" if bt.get("ligado")
                else "<span class='badge b-er'>desligado</span>")
    modem_badge = ("<span class='badge b-ok'>presente</span>"
                   if os.path.exists(eng.QMI_DEV)
                   else "<span class='badge b-er'>ausente</span>")
    cache = ULTIMO_DIAG.get("áudio (loopback)")
    if cache:
        cls = {"ok": "b-ok", "falha": "b-er",
               "nao_testavel": "b-av"}.get(cache["status"], "b-av")
        audio_badge = f"<span class='badge {cls}'>{html.escape(cache['status'])}</span>"
    else:
        audio_badge = "<span class='badge b-av'>não testado</span>"
    return (f"<a class='linha' href='/bluetooth'><span>🔵 Bluetooth</span>{bt_badge}</a>"
            f"<a class='linha' href='/modem'><span>📶 Modem 4G</span>{modem_badge}</a>"
            f"<a class='linha' href='/audio'><span>🎧 Áudio</span>{audio_badge}</a>")


def tela_status(extra=""):
    st = eng.status()
    sa = eng.saude_sistema()
    if st["internet"]:
        badge = "<span class='badge b-ok'>conectado à internet</span>"
        linha = "Seu dongle está conectado à internet."
    else:
        badge = "<span class='badge b-er'>sem internet</span>"
        linha = ("Não conseguimos conectar à internet. "
                 "Verifique o status do seu chip 4G.")
    modo = {"hotspot": "Ponto de acesso (hotspot)",
            "wifi": "Conectado a um Wi-Fi",
            "indefinido": "—"}.get(st["modo"], st["modo"])
    ssid = (f"<p>Rede do hotspot: <b>{html.escape(st['hotspot_ssid'])}</b></p>"
            if st.get("hotspot_ssid") else "")

    ram_disp_pct = (round(sa["ram"]["disponivel_kb"] / sa["ram"]["total_kb"] * 100)
                    if sa["ram"]["total_kb"] else None)
    disco_pct = sa["disco_raiz"]["usado_pct"]
    temp_cpu = sa["temp_cpu_c"]
    trip = sa["temp_cpu_trip_c"] or 75
    tiles = f"""
      <div class='stats'>
        <div class='stat'><span>CPU (1 min)</span>
          <b>{sa['cpu']['carga_1m']:.2f} / {sa['cpu']['nucleos']} núcleos</b></div>
        <div class='stat'><span>RAM livre</span>
          <b class='{_nivel(ram_disp_pct, 15, 5, menor_pior=True)}'>
          {ram_disp_pct if ram_disp_pct is not None else '?'}%</b></div>
        <div class='stat'><span>Disco (raiz)</span>
          <b class='{_nivel(disco_pct, 85, 95)}'>{disco_pct}% usado</b></div>
        <div class='stat'><span>Temperatura</span>
          <b class='{_nivel(temp_cpu, trip - 10, trip)}'>
          {f"{temp_cpu:.0f}°C" if temp_cpu is not None else '?'}</b></div>
      </div>
      <details style='margin-top:10px'>
        <summary style='color:var(--mut);font-size:.85em;cursor:pointer'>
        Ver tudo</summary>
        <p style='font-size:.85em;color:var(--mut)'>
        {"".join(f"{html.escape(k)}: {v}°C<br>" for k, v in sa['temperaturas_c'].items())}
        Disco raiz: {sa['disco_raiz']['usado_gb']}GB de {sa['disco_raiz']['total_gb']}GB<br>
        {f"Disco /boot: {sa['disco_boot']['usado_pct']}% de {sa['disco_boot']['total_mb']}MB<br>" if sa.get('disco_boot') else ""}
        Ligado há {sa['uptime_s'] // 3600}h{(sa['uptime_s'] % 3600) // 60}min</p>
      </details>"""

    return page(f"""
      <div class='card'>
        <h1>🔌 OpenDongle</h1>
        {badge}
        <p>{linha}</p>
        <p>Modo atual: <b>{modo}</b></p>{ssid}
        {extra}
        <p style='margin-top:16px'>Para acessar este painel a qualquer
        momento, digite <b>opendongle.local</b> (ou {IP}).</p>
      </div>
      <div class='card'>
        <h2>📊 Saúde do sistema</h2>
        {tiles}
      </div>
      <div class='card'>
        <h2>🧩 Hardware</h2>
        {_resumo_hardware()}
      </div>
      <div class='card'>
        <h2>Configurar</h2>
        <a class='btn' href='/config'><button class='sec'>⚙️ Abrir
        configurações</button></a>
      </div>""")


def tela_escolha():
    return page("""
      <div class='card'>
        <h1>🔌 OpenDongle</h1>
        <p>Como você quer usar seu dongle?</p>
        <a class='btn' href='/status'><button>📡 Deixar como hotspot de
        internet</button></a>
        <a class='btn' href='/wifi'><button class='sec'>📶 Conectar o
        dongle a uma rede Wi-Fi</button></a>
      </div>""")


def tela_wifi(erro=""):
    r = eng.listar_wifi()
    ops = "".join(
        f"<option value='{html.escape(x['ssid'], quote=True)}'>"
        f"{html.escape(x['ssid'])} ({x['sinal']}%)</option>"
        for x in r.get("redes", [])) or "<option value=''>— nenhuma vista —</option>"
    aviso_scan = (f"<div class='aviso'>{html.escape(r['aviso'])}</div>"
                  if r.get("aviso") else "")
    return page(f"""
      <div class='card'>
        <h1>Conectar a um Wi-Fi</h1>
        <form method='post' action='/wifi'>
          <label>Redes encontradas</label>
          <select name='ssid_lista'>{ops}</select>
          <label>Ou digite o nome da rede (se não apareceu acima)</label>
          <input name='ssid_manual' placeholder='Nome exato do Wi-Fi'
                 autocomplete='off'>
          <label>Senha do Wi-Fi</label>
          <input name='senha' type='password' placeholder='(vazio se aberta)'>
          {aviso_scan}
          <div class='aviso'>Ao conectar, o hotspot será desligado
          (limitação do chip). O acesso pelo cabo USB continua.</div>
          <button>Conectar</button>
        </form>
        {msg(erro,'er')}
        <a class='btn' href='/'><button class='sec'>Voltar</button></a>
      </div>""")


def tela_config(logado, m=""):
    if not logado:
        return page(f"""
          <div class='card'>
            <h1>⚙️ Configurações</h1>
            <p>Entre com a senha de administração para continuar.</p>
            <form method='post' action='/login'>
              <label>Senha de administração</label>
              <input name='senha' type='password' required>
              <button>Entrar</button>
            </form>{msg(m,'er')}
          </div>""")
    st = eng.status()
    return page(f"""
      <div class='card'>
        <h1>⚙️ Configurações</h1>
        <p>Modo: <b>{st['modo']}</b> · Internet:
        <b>{'sim' if st['internet'] else 'não'}</b></p>{msg(m,'ok')}
      </div>
      <div class='card'>
        <h2>📡 Nome e senha do hotspot</h2>
        <form method='post' action='/set-hotspot'>
          <label>Nome da rede (SSID)</label>
          <input name='ssid' value='{html.escape(st.get('hotspot_ssid') or '')}'
                 maxlength='32' required>
          <label>Senha (8 a 63 caracteres)</label>
          <input name='senha' type='password' minlength='8' maxlength='63'
                 required>
          <div class='aviso'>Ao salvar, a rede reinicia. Você vai precisar
          reconectar no Wi-Fi com o novo nome/senha e abrir
          opendongle.local de novo.</div>
          <button>Salvar hotspot</button>
        </form>
      </div>
      <div class='card'>
        <h2>🔀 Modo de operação</h2>
        <div class='row'>
          <form method='post' action='/mode-hotspot'>
            <button class='sec'>Virar hotspot</button></form>
          <a class='btn' href='/wifi'><button class='sec'>Conectar
          Wi-Fi</button></a>
        </div>
      </div>
      <div class='card'>
        <h2>🔑 Senha de administração</h2>
        <form method='post' action='/set-password'>
          <label>Nova senha (mín. 6)</label>
          <input name='senha' type='password' minlength='6' required>
          <button>Trocar senha</button>
        </form>
      </div>
      <div class='card'>
        <h2>🧩 Hardware</h2>
        <a class='btn' href='/bluetooth'><button class='sec'>🔵 Bluetooth</button></a>
        <a class='btn' href='/modem'><button class='sec'>📶 Modem 4G</button></a>
        <a class='btn' href='/audio'><button class='sec'>🎧 Áudio</button></a>
        <a class='btn' href='/diagnostico'><button class='sec'>🩺
        Diagnóstico completo</button></a>
      </div>""")


def _linha_dispositivo(d, acao=None):
    """acao = (rota, rotulo) do botão, só aparece se logado (quem chama
    já decide isso antes de passar acao ou não)."""
    botao = ""
    if acao:
        botao = (f"<form method='post' action='{acao[0]}' style='margin:0'>"
                 f"<input type='hidden' name='mac' "
                 f"value='{html.escape(d['mac'], quote=True)}'>"
                 f"<button class='sec' style='width:auto;margin:0;"
                 f"padding:6px 12px'>{acao[1]}</button></form>")
    return (f"<div class='linha'><span>{html.escape(d['nome'])}<br>"
            f"<small style='color:var(--mut)'>{html.escape(d['mac'])}</small>"
            f"</span>{botao}</div>")


def tela_bluetooth(logado, m="", erro=False, encontrados=None):
    bt = eng.bluetooth_status()
    if not bt["ok"]:
        return page(f"""<div class='card'><h1>🔵 Bluetooth</h1>
          {msg(bt['erro'], 'er')}
          <a class='btn' href='/status'><button class='sec'>Voltar</button></a>
          </div>""")

    estado = ("<span class='badge b-ok'>ligado</span>" if bt["ligado"]
              else "<span class='badge b-er'>desligado</span>")
    conectados = ", ".join(html.escape(d["nome"]) for d in bt["conectados"]) or "nenhum"
    pareados_html = "".join(_linha_dispositivo(
        d, ("/bluetooth-forget", "Esquecer") if logado else None)
        for d in bt["pareados"]) or \
        "<p style='color:var(--mut)'>Nenhum aparelho pareado.</p>"

    encontrados_html = ""
    if encontrados is not None:
        if encontrados:
            encontrados_html = ("<div class='card'><h2>Encontrados</h2>" +
                "".join(_linha_dispositivo(d, ("/bluetooth-pair", "Parear"))
                        for d in encontrados) + "</div>")
        else:
            encontrados_html = ("<div class='card'><p style='color:var(--mut)'>"
                "Nada encontrado. Deixe o aparelho em modo de pareamento "
                "e tente de novo.</p></div>")

    acoes = ""
    if logado:
        acoes = f"""
      <div class='card'>
        <h2>Ações</h2>
        <div class='row'>
          <form method='post' action='/bluetooth-power'>
            <input type='hidden' name='ligar' value='{"0" if bt["ligado"] else "1"}'>
            <button class='sec'>{"Desligar" if bt["ligado"] else "Ligar"} rádio</button>
          </form>
          <form method='post' action='/bluetooth-scan'
                onsubmit="this.querySelector('button').textContent='Procurando…';this.querySelector('button').disabled=true">
            <button class='sec'>Escanear (8s)</button>
          </form>
        </div>
        {"<div class='aviso'>Desligar aqui é temporário — volta sozinho "
         "no próximo boot ou ao reconectar o modem.</div>" if bt["ligado"] else ""}
      </div>"""

    return page(f"""
      <div class='card'>
        <h1>🔵 Bluetooth</h1>
        {estado}
        <p>Nome do dongle: <b>{html.escape(bt['nome'])}</b></p>
        <p>Conectado agora: {conectados}</p>
        {msg(m, 'er' if erro else 'ok')}
      </div>
      <div class='card'>
        <h2>Pareados</h2>
        {pareados_html}
      </div>
      {acoes}
      {encontrados_html}
      <div class='card'>
        <a class='btn' href='/status'><button class='sec'>Voltar</button></a>
      </div>""")


def tela_modem(logado, m="", erro=False):
    md = eng.modem_status()
    if not md.get("presente"):
        corpo = "<p>Nenhum modem detectado (porta QMI ausente).</p>"
    else:
        if md["sim_presente"] is None:
            sim = "<span class='badge b-av'>não deu pra ler agora</span>"
        elif md["sim_presente"]:
            sim = "<span class='badge b-ok'>SIM presente</span>"
        else:
            sim = "<span class='badge b-av'>sem SIM</span>"
        reg = ("<span class='badge b-ok'>registrado</span>" if md["registrado"]
               else "<span class='badge b-er'>não registrado</span>")
        sinal = f"{md['rssi_dbm']} dBm" if md["rssi_dbm"] is not None else "—"
        imei_linha = (f"<p>IMEI: <b>{html.escape(md['imei'] or '—')}</b></p>"
                      if logado and md.get("imei") else "")
        corpo = f"""
        {sim} {reg}
        <p>Operadora: <b>{html.escape(md['operadora'] or '—')}</b></p>
        <p>Sinal: <b>{html.escape(sinal)}</b></p>
        <p>Modo do rádio: <b>{html.escape(md['modo_operacao'] or '—')}</b></p>
        {imei_linha}"""

    acoes = ""
    if logado:
        acoes = """
      <div class='card'>
        <h2>Reconectar</h2>
        <form method='post' action='/modem-reconectar'>
          <div class='aviso'>Reaplica grupos, Bluetooth, papel USB e o
          4G — leva alguns segundos.</div>
          <button class='sec'>Reconectar 4G</button>
        </form>
      </div>
      <div class='card'>
        <h2>Adicionar operadora (APN)</h2>
        <form method='post' action='/modem-set-apn'>
          <label>MCC-MNC (ex: 724-01)</label>
          <input name='mcc_mnc' placeholder='724-01' required>
          <label>APN</label>
          <input name='apn' placeholder='zap.vivo.com.br' required>
          <button>Salvar</button>
        </form>
      </div>"""

    return page(f"""
      <div class='card'>
        <h1>📶 Modem 4G</h1>
        {corpo}
        {msg(m, 'er' if erro else 'ok')}
      </div>
      {acoes}
      <div class='card'>
        <a class='btn' href='/status'><button class='sec'>Voltar</button></a>
      </div>""")


def tela_audio(logado, m="", erro=False):
    cache = ULTIMO_DIAG.get("áudio (loopback)")
    if cache:
        cls = {"ok": "b-ok", "falha": "b-er",
               "nao_testavel": "b-av"}.get(cache["status"], "b-av")
        quando = time.strftime("%d/%m %H:%M", time.localtime(cache["quando"]))
        resultado = f"""
        <span class='badge {cls}'>{html.escape(cache['status'])}</span>
        <p>{html.escape(cache['detalhe'])}</p>
        <p style='color:var(--mut);font-size:.85em'>Testado às {quando}</p>"""
    else:
        resultado = "<p style='color:var(--mut)'>Ainda não testado.</p>"

    acao = ("<div class='card'><form method='post' action='/audio-test'>"
            "<button class='sec'>Testar áudio agora</button></form></div>"
            if logado else "")

    return page(f"""
      <div class='card'>
        <h1>🎧 Áudio</h1>
        <p style='color:var(--mut)'>Esse dongle não tem placa de som fixa
        nem mixer — áudio só existe quando algo está em uso (fone/mic
        USB, ou este teste de loopback). Por isso não tem
        "configurações" de verdade, só um teste.</p>
        {resultado}
        {msg(m, 'er' if erro else 'ok')}
      </div>
      {acao}
      <div class='card'>
        <a class='btn' href='/status'><button class='sec'>Voltar</button></a>
      </div>""")


def tela_diagnostico(logado):
    icone = {"ok": "b-ok", "falha": "b-er", "nao_testavel": "b-av"}
    if ULTIMO_DIAG:
        linhas = "".join(
            f"<div class='linha'><span>{html.escape(nome)}</span>"
            f"<span class='badge {icone.get(r['status'], 'b-av')}'>"
            f"{html.escape(r['status'])}</span></div>"
            f"<p style='color:var(--mut);font-size:.8em;margin:-6px 0 10px'>"
            f"{html.escape(r['detalhe'])}</p>"
            for nome, r in ULTIMO_DIAG.items())
        quando = max((r["quando"] for r in ULTIMO_DIAG.values()), default=None)
        rodape = (f"<p style='color:var(--mut);font-size:.85em'>Última vez: "
                  f"{time.strftime('%d/%m %H:%M', time.localtime(quando))}</p>"
                  if quando else "")
    else:
        linhas = "<p style='color:var(--mut)'>Ainda não rodado.</p>"
        rodape = ""

    acao = ("<div class='card'><form method='post' action='/diagnostico'>"
            "<button class='sec'>Rodar diagnóstico completo</button></form></div>"
            if logado else "")

    return page(f"""
      <div class='card'>
        <h1>🩺 Diagnóstico de hardware</h1>
        {linhas}
        {rodape}
      </div>
      {acao}
      <div class='card'>
        <a class='btn' href='/status'><button class='sec'>Voltar</button></a>
      </div>""")


# ---------- servidor ----------
class Painel(BaseHTTPRequestHandler):
    def _send(self, corpo, code=200, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)

    def _redir(self, dest, cookie=None):
        self.send_response(302)
        self.send_header("Location", dest)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _logado(self):
        c = self.headers.get("Cookie", "")
        return any(x.strip().removeprefix("s=") in SESSOES
                   for x in c.split(";") if x.strip().startswith("s="))

    def _form(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        d = urllib.parse.parse_qs(self.rfile.read(n).decode())
        return {k: v[0] for k, v in d.items()}

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in DETECCAO:                     # portal cativo
            return self._redir(f"http://{IP}/")
        host = self.headers.get("Host", "").split(":")[0]
        if host not in (IP, "opendongle.local", "opendongle"):
            return self._redir(f"http://{IP}/")
        if path == "/" :
            return self._send(tela_escolha())
        if path == "/status":
            return self._send(tela_status())
        if path == "/wifi":
            return self._send(tela_wifi())
        if path == "/config":
            return self._send(tela_config(self._logado()))
        if path == "/bluetooth":
            return self._send(tela_bluetooth(self._logado()))
        if path == "/modem":
            return self._send(tela_modem(self._logado()))
        if path == "/audio":
            return self._send(tela_audio(self._logado()))
        if path == "/diagnostico":
            return self._send(tela_diagnostico(self._logado()))
        return self._redir("/")

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        f = self._form()
        if path == "/login":
            # valida a senha de admin reusando o sistema: tenta um no-op
            # que só root/senha-correta faria? Aqui validamos via PAM
            # simplificado: a troca real de senha exige root de qualquer
            # forma. Para o login do painel, conferimos contra /etc/shadow.
            if _checa_admin(f.get("senha", "")):
                tok = secrets.token_urlsafe(24)
                SESSOES.add(tok)
                return self._redir("/config", f"s={tok}; Path=/; HttpOnly")
            return self._send(tela_config(False, "Senha incorreta."))
        if path == "/wifi":
            # aceita o SSID digitado manualmente OU o escolhido na lista
            ssid = (f.get("ssid_manual") or "").strip() or \
                   (f.get("ssid_lista") or "").strip() or \
                   (f.get("ssid") or "").strip()
            r = eng.connect_wifi(ssid, f.get("senha", ""))
            if r["ok"]:
                return self._send(tela_status(
                    msg("Conectado! " + r.get("aviso", ""))))
            return self._send(tela_wifi(r["erro"]))
        # daqui: ações protegidas
        if not self._logado():
            return self._redir("/config")
        if path == "/set-hotspot":
            r = eng.set_hotspot(f.get("ssid"), f.get("senha"))
            return self._send(tela_config(True,
                (r.get("aviso") if r["ok"] else r["erro"])))
        if path == "/mode-hotspot":
            r = eng.mode_hotspot()
            return self._send(tela_config(True,
                "Hotspot ativado." if r["ok"] else r["erro"]))
        if path == "/set-password":
            r = eng.set_password(f.get("senha", ""))
            return self._send(tela_config(True,
                (r.get("aviso") if r["ok"] else r["erro"])))
        if path == "/bluetooth-power":
            r = eng.bluetooth_power(f.get("ligar") == "1")
            return self._send(tela_bluetooth(True,
                m=(r.get("aviso") if r["ok"] else r["erro"]), erro=not r["ok"]))
        if path == "/bluetooth-scan":
            r = eng.bluetooth_scan()
            return self._send(tela_bluetooth(True,
                encontrados=r.get("encontrados", [])))
        if path == "/bluetooth-pair":
            r = eng.bluetooth_pair(f.get("mac", ""))
            return self._send(tela_bluetooth(True,
                m=(r.get("aviso") if r["ok"] else r["erro"]), erro=not r["ok"]))
        if path == "/bluetooth-forget":
            r = eng.bluetooth_forget(f.get("mac", ""))
            return self._send(tela_bluetooth(True,
                m=(r.get("aviso") if r["ok"] else r["erro"]), erro=not r["ok"]))
        if path == "/modem-reconectar":
            r = eng.modem_reconectar()
            return self._send(tela_modem(True,
                m=(r.get("aviso") if r["ok"] else r["erro"]), erro=not r["ok"]))
        if path == "/modem-set-apn":
            r = eng.modem_set_apn(f.get("mcc_mnc", ""), f.get("apn", ""))
            return self._send(tela_modem(True,
                m=(r.get("aviso") if r["ok"] else r["erro"]), erro=not r["ok"]))
        if path == "/audio-test":
            status_teste, detalhe = diag.teste_audio()
            ULTIMO_DIAG["áudio (loopback)"] = {
                "status": status_teste, "detalhe": detalhe, "quando": time.time()}
            return self._send(tela_audio(True))
        if path == "/diagnostico":
            # roda como PROCESSO SEPARADO, não import in-process: o
            # teste de modem usa signal.alarm() como watchdog, que só
            # funciona na thread principal — e aqui estamos numa thread
            # do ThreadingHTTPServer, nunca a principal.
            diag_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "opendongle_diag.py")
            try:
                r = subprocess.run(["python3", diag_path, "--json"],
                                   capture_output=True, text=True, timeout=30)
                resultados = json.loads(r.stdout)
            except Exception:
                resultados = []
            for res in resultados:
                ULTIMO_DIAG[res["nome"]] = {"status": res["status"],
                    "detalhe": res["detalhe"], "quando": time.time()}
            return self._send(tela_diagnostico(True))
        return self._redir("/")

    def log_message(self, *a):
        pass


def _hash_shadow(usuario):
    """Lê o hash de /etc/shadow direto (rodamos como root). Os módulos
    'crypt' e 'spwd' que faziam isso foram REMOVIDOS do Python 3.12/3.13
    (PEP 594) — essa imagem já roda 3.13, então o jeito antigo sempre
    retornava False silenciosamente (login nunca funcionava)."""
    try:
        with open("/etc/shadow") as f:
            for linha in f:
                campos = linha.split(":")
                if campos[0] == usuario:
                    return campos[1]
    except OSError:
        pass
    return None


def _checa_admin(senha):
    """Confere a senha de admin contra /etc/shadow, chamando crypt(3) da
    libc via ctypes — substitui o módulo 'crypt' removido do Python.
    O próprio hash existente serve de 'salt' pro crypt() (inclui
    algoritmo e parâmetros, ex: yescrypt '$y$...'), igual o módulo antigo
    já fazia por baixo dos panos."""
    try:
        import ctypes
        import hmac
        reg = _hash_shadow(eng.ADMIN_USER)
        if not reg or reg in ("", "!", "*", "!!"):
            return False
        libc = ctypes.CDLL("libcrypt.so.1")
        libc.crypt.restype = ctypes.c_char_p
        libc.crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        calc = libc.crypt(senha.encode(), reg.encode())
        return calc is not None and hmac.compare_digest(calc.decode(), reg)
    except Exception:
        return False


def servir():
    ThreadingHTTPServer(("0.0.0.0", 80), Painel).serve_forever()


if __name__ == "__main__":
    servir()
