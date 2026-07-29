#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
portal.py — Portal cativo do OpenStick (roda NO DONGLE como serviço root)

Comportamento:
- Enquanto ninguém completar o portal desde que o dongle foi LIGADO
  (flag em /run, que zera a cada energização), todo DNS do hotspot
  aponta para o dongle e todo HTTP cai na tela de login.
- Login = credenciais do próprio sistema (ex.: user/1), validadas
  contra /etc/shadow. Sem senha extra para gerenciar.
- Após login, duas rotas:
    1) Conectar o dongle a um Wi-Fi existente (vira CLIENTE; o
       hotspot cai — limitação do chip wcn36xx, avisada na tela).
    2) Continuar em modo hotspot compartilhando o 4G.
- Ao concluir qualquer rota, o sequestro de DNS é desfeito e os
  clientes navegam normalmente.

Somente biblioteca padrão (nada de pip no dongle).
"""

import crypt
import hmac
import html
import json
import os
import secrets
import spwd
import subprocess
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

IP = "192.168.100.1"
FLAG = "/run/portal_done"                 # /run é tmpfs: zera ao ligar
CAPTIVE_CONF = "/etc/NetworkManager/dnsmasq-shared.d/captive.conf"
SESSOES = set()                           # tokens de sessão em memória

# Endpoints que os sistemas operacionais usam para detectar portal cativo
DETECCAO = ("/generate_204", "/gen_204", "/hotspot-detect.html",
            "/ncsi.txt", "/connecttest.txt", "/success.txt",
            "/canonical.html", "/check_network_status.txt")


def portal_concluido():
    return os.path.exists(FLAG)


def concluir_portal():
    open(FLAG, "w").write("ok")
    # Desfaz o sequestro de DNS e recarrega a rede (hotspot pisca ~10s)
    if os.path.exists(CAPTIVE_CONF):
        os.remove(CAPTIVE_CONF)
        subprocess.Popen(["systemctl", "restart", "NetworkManager"])


def checar_login(usuario, senha):
    """Valida contra /etc/shadow (rodamos como root)."""
    try:
        registro = spwd.getspnam(usuario).sp_pwdp
    except KeyError:
        return False
    if registro in ("", "!", "*", "!!"):
        return False
    return hmac.compare_digest(crypt.crypt(senha, registro), registro)


def redes_wifi():
    """Lista SSIDs visíveis via nmcli, sem duplicatas, por sinal."""
    r = subprocess.run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY",
                        "device", "wifi", "list", "--rescan", "yes"],
                       capture_output=True, text=True, timeout=30)
    vistos, redes = set(), []
    for linha in (r.stdout or "").splitlines():
        partes = linha.split(":")
        if len(partes) >= 2 and partes[0] and partes[0] not in vistos:
            vistos.add(partes[0])
            redes.append({"ssid": partes[0],
                          "sinal": partes[1],
                          "seg": ":".join(partes[2:]) or "aberta"})
    redes.sort(key=lambda x: -int(x["sinal"] or 0))
    return redes[:20]


def conectar_wifi(ssid, senha):
    """Agenda a troca para modo cliente APÓS a resposta HTTP sair
    (senão o hotspot cai antes do usuário ver a confirmação)."""
    cmd = ["nmcli", "device", "wifi", "connect", ssid]
    if senha:
        cmd += ["password", senha]
    # systemd-run desacopla do portal e espera 5s antes de trocar o modo
    subprocess.Popen(["systemd-run", "--on-active=5", "--collect"] + cmd)


# ------------------------------------------------------------- HTML
ESTILO = """<style>
body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;
 display:flex;justify-content:center;padding:24px}
.card{background:#1e293b;border-radius:14px;padding:28px;max-width:420px;
 width:100%}h1{font-size:1.3em;margin:0 0 6px}p{color:#94a3b8;font-size:.92em}
input,select{width:100%;padding:11px;margin:6px 0;border-radius:8px;
 border:1px solid #334155;background:#0f172a;color:#e2e8f0;box-sizing:border-box}
button{width:100%;padding:12px;margin-top:12px;border:0;border-radius:8px;
 background:#3b82f6;color:#fff;font-size:1em;cursor:pointer}
.sec{background:#334155}.aviso{background:#422006;border:1px solid #a16207;
 border-radius:8px;padding:10px;font-size:.88em;margin-top:10px}
.erro{color:#f87171;font-size:.9em}</style>"""


def pagina(corpo, titulo="OpenStick"):
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{titulo}</title>{ESTILO}</head>"
            f"<body><div class='card'>{corpo}</div></body></html>").encode()


def pg_login(erro=""):
    e = f"<p class='erro'>{erro}</p>" if erro else ""
    return pagina(f"""
      <h1>🔌 OpenStick</h1>
      <p>Você é o primeiro a conectar desde que o modem foi ligado.
      Entre com as credenciais do sistema para configurá-lo.</p>{e}
      <form method='post' action='/login'>
        <input name='usuario' placeholder='Usuário' autocomplete='off' required>
        <input name='senha' type='password' placeholder='Senha' required>
        <button>Entrar</button></form>""")


def pg_menu():
    return pagina("""
      <h1>Como usar a internet?</h1>
      <form method='get' action='/wifi'>
        <button>📶 Conectar o modem a um Wi-Fi existente</button></form>
      <form method='post' action='/hotspot'>
        <button class='sec'>📡 Continuar como hotspot 4G</button></form>
      <p class='aviso'>⚠️ Ao escolher um Wi-Fi, este hotspot será
      DESLIGADO (limitação do chip) e o modem entrará na rede escolhida.
      O acesso via cabo USB continua funcionando sempre.</p>""")


def pg_wifi(redes):
    ops = "".join(f"<option value='{html.escape(r['ssid'], quote=True)}'>"
                  f"{html.escape(r['ssid'])} ({r['sinal']}% · {html.escape(r['seg'])})</option>"
                  for r in redes) or "<option value=''>nenhuma rede vista</option>"
    return pagina(f"""
      <h1>Escolha a rede</h1>
      <form method='post' action='/wifi'>
        <select name='ssid'>{ops}</select>
        <input name='senha' type='password'
               placeholder='Senha do Wi-Fi (vazio se aberta)'>
        <button>Conectar</button></form>
      <form method='get' action='/menu'>
        <button class='sec'>Voltar</button></form>""")


PG_WIFI_OK = pagina("""
      <h1>✅ Trocando de modo...</h1>
      <p>Em ~5 segundos este hotspot vai desligar e o modem entrará na
      rede escolhida. Para acessá-lo depois: pelo cabo USB
      (192.168.100.1) ou pelo IP que o roteador der a ele
      (procure por 'openstick' na lista do roteador).</p>""")

PG_HOTSPOT_OK = pagina("""
      <h1>✅ Modo hotspot ativo</h1>
      <p>O modem seguirá compartilhando o 4G nesta rede. A rede vai
      piscar por ~10s enquanto o DNS é normalizado — depois disso,
      internet liberada para todos. Bom uso!</p>""")

PG_JA_FEITO = pagina("""
      <h1>OpenStick</h1><p>Modem já configurado nesta energização.
      Administração: <code>ssh user@192.168.100.1</code></p>""")


# ------------------------------------------------------------- servidor
class Portal(BaseHTTPRequestHandler):
    def _resp(self, corpo, tipo="text/html", cod=200, extra=None):
        self.send_response(cod)
        self.send_header("Content-Type", f"{tipo}; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)

    def _redir(self, destino):
        self.send_response(302)
        self.send_header("Location", destino)
        self.end_headers()

    def _logado(self):
        cookies = self.headers.get("Cookie", "")
        return any(c.strip().removeprefix("s=") in SESSOES
                   for c in cookies.split(";") if c.strip().startswith("s="))

    def _form(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        dados = urllib.parse.parse_qs(self.rfile.read(n).decode())
        return {k: v[0] for k, v in dados.items()}

    def do_GET(self):
        caminho = urllib.parse.urlparse(self.path).path
        # Detecção de portal pelos sistemas operacionais
        if caminho in DETECCAO:
            if portal_concluido():
                return self._resp(b"", "text/plain", 204)
            return self._redir(f"http://{IP}/")
        if portal_concluido():
            return self._resp(PG_JA_FEITO)
        # Qualquer host/rota desconhecida cai no portal
        if self.headers.get("Host", "").split(":")[0] not in (IP, "openstick"):
            return self._redir(f"http://{IP}/")
        if caminho == "/menu" and self._logado():
            return self._resp(pg_menu())
        if caminho == "/wifi" and self._logado():
            return self._resp(pg_wifi(redes_wifi()))
        return self._resp(pg_login())

    def do_POST(self):
        caminho = urllib.parse.urlparse(self.path).path
        f = self._form()
        if caminho == "/login":
            if checar_login(f.get("usuario", ""), f.get("senha", "")):
                token = secrets.token_urlsafe(24)
                SESSOES.add(token)
                self.send_response(302)
                self.send_header("Set-Cookie", f"s={token}; Path=/; HttpOnly")
                self.send_header("Location", "/menu")
                return self.end_headers()
            return self._resp(pg_login("Usuário ou senha incorretos."))
        if not self._logado():
            return self._redir("/")
        if caminho == "/wifi":
            conectar_wifi(f.get("ssid", ""), f.get("senha", ""))
            concluir_portal()
            return self._resp(PG_WIFI_OK)
        if caminho == "/hotspot":
            concluir_portal()
            return self._resp(PG_HOTSPOT_OK)
        self._redir("/")

    def log_message(self, *a):   # silencia log por requisição
        pass


if __name__ == "__main__":
    # Instala o sequestro de DNS se o portal ainda está pendente nesta
    # energização (dnsmasq do NetworkManager responde tudo com nosso IP)
    if not portal_concluido():
        os.makedirs(os.path.dirname(CAPTIVE_CONF), exist_ok=True)
        conf_desejada = f"address=/#/{IP}\n"
        atual = (open(CAPTIVE_CONF).read()
                 if os.path.exists(CAPTIVE_CONF) else "")
        if atual != conf_desejada:
            open(CAPTIVE_CONF, "w").write(conf_desejada)
            subprocess.run(["systemctl", "restart", "NetworkManager"])
    ThreadingHTTPServer(("0.0.0.0", 80), Portal).serve_forever()
