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
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opendongle_engine as eng

IP = "192.168.100.1"
SESSOES = set()
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
 8px;padding:10px;font-size:.85em;color:#fcd34d;margin-top:12px}</style>"""


def page(corpo, titulo="OpenDongle"):
    return (f"<!doctype html><html lang='pt-br'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,"
            f"initial-scale=1'><title>{titulo}</title>{ESTILO}</head>"
            f"<body><div class='wrap'>{corpo}</div></body></html>").encode()


def msg(txt, tipo="ok"):
    return f"<div class='msg {tipo}'>{html.escape(txt)}</div>" if txt else ""


# ---------- telas ----------
def tela_status(extra=""):
    st = eng.status()
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
        return self._redir("/")

    def log_message(self, *a):
        pass


def _checa_admin(senha):
    """Confere a senha de admin contra /etc/shadow (rodamos como root)."""
    try:
        import crypt
        import spwd
        import hmac
        reg = spwd.getspnam(eng.ADMIN_USER).sp_pwdp
        if reg in ("", "!", "*", "!!"):
            return False
        return hmac.compare_digest(crypt.crypt(senha, reg), reg)
    except Exception:
        return False


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 80), Painel).serve_forever()
