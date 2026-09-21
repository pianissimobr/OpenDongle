#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongle_localizar.py — acha o dongle na rede quando o mDNS falha (roda no PC)
==================================================================================
Mesmo padrão de "motor único + HTML" que o resto do projeto já usa em
opendongle_web.py, só que espelhado pro lado do PC: um servidor HTTP local
serve a página, e é ESSE Python — não o navegador, que não tem acesso a
socket — quem manda o broadcast UDP de verdade na rede e recebe a resposta
de opendongle_discovery.py (rodando no dongle).

Uso:
  python3 opendongle_localizar.py

Abre sozinho http://127.0.0.1:8765 no navegador padrão. Clique em
"Procurar dongle" — o Python local dispara o probe, escuta ~2s e mostra
quem respondeu.

Broadcast dirigido por interface: o 255.255.255.255 sai só pela interface
da rota padrão. Num PC com várias placas (Wi-Fi, cabo, USB do dongle, VPN,
Docker), o dongle numa rede que não é a padrão nunca ouviria o probe. Então
o probe vai pro broadcast de CADA interface IPv4 (ex.: 192.168.5.255), com o
socket preso ao IP dela, pro sistema usar a placa certa — além do
192.168.100.255 (a rede USB do OpenDongle) e do broadcast geral. Sem
dependências: lê 'ip -j' (Linux), 'ifconfig' (macOS/BSD) ou 'ipconfig'
(Windows, em qualquer idioma).
"""
import http.server
import ipaddress
import json
import re
import selectors
import socket
import subprocess
import threading
import time
import webbrowser

PORTA_HTTP = 8765
PORTA_DESCOBERTA = 40404
PROBE = b"OPENDONGLE_DISCOVER_V1"
DESTINOS_BROADCAST = ["192.168.100.255", "255.255.255.255"]
TIMEOUT_BUSCA = 2.0

ESTILO = """
:root{--bg:#0f1115;--card:#171a21;--in:#1d2129;--br:#2a2f3a;--tx:#e6e8eb;
--mut:#9aa2af;--ok:#34d399;--er:#f87171;--ac:#60a5fa}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--tx);font-family:system-ui,sans-serif;
max-width:640px;margin:0 auto;padding:24px 16px}
h1{font-size:1.4em;margin:0 0 4px}
p.sub{color:var(--mut);margin:0 0 20px}
.card{background:var(--card);border:1px solid var(--br);border-radius:14px;
padding:18px;margin-bottom:14px}
button{background:var(--ac);color:#0b1220;border:none;border-radius:10px;
padding:12px 18px;font-size:1em;font-weight:600;cursor:pointer}
button:disabled{opacity:.6;cursor:default}
.item{display:flex;justify-content:space-between;align-items:center;
background:var(--in);border:1px solid var(--br);border-radius:10px;
padding:10px 14px;margin-top:10px}
.item a{color:var(--ac);text-decoration:none;font-weight:600}
.mut{color:var(--mut);font-size:.9em}
.vazio{color:var(--mut);margin-top:14px}
"""

PAGINA = f"""<!doctype html>
<html lang="pt-br"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Localizar OpenDongle</title>
<style>{ESTILO}</style>
</head><body>
<h1>🔎 Localizar OpenDongle</h1>
<p class="sub">Quando opendongle.local não resolve, isso acha o dongle
pelo IP direto na rede local — sem precisar de USB nem entrar no roteador.</p>
<div class="card">
<button id="btn" onclick="buscar()">Procurar dongle</button>
<div id="resultado"></div>
</div>
<script>
async function buscar() {{
  const btn = document.getElementById('btn');
  const out = document.getElementById('resultado');
  btn.disabled = true;
  btn.textContent = 'Procurando...';
  out.innerHTML = '';
  try {{
    const r = await fetch('/buscar', {{method: 'POST'}});
    const dados = await r.json();
    if (dados.achados.length === 0) {{
      out.innerHTML = '<p class="vazio">Nenhum dongle respondeu. ' +
        'Confirme que ele está ligado, na mesma rede, e com o painel ' +
        'atualizado (opendongle_discovery.service precisa estar ativo).</p>';
    }} else {{
      out.innerHTML = dados.achados.map(d =>
        `<div class="item"><div><a href="http://${{d.ip}}/" target="_blank">` +
        `${{d.ip}}</a><div class="mut">${{d.host}}${{d.id ? ' · ' + d.id.slice(0, 6) : ''}}</div></div></div>`
      ).join('');
    }}
  }} catch (e) {{
    out.innerHTML = '<p class="vazio">Erro ao buscar: ' + e + '</p>';
  }}
  btn.disabled = false;
  btn.textContent = 'Procurar de novo';
}}
</script>
</body></html>
"""


def _rodar(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _redes_de_texto(texto):
    """Pares IP + máscara num texto de ifconfig/ipconfig, em qualquer idioma:
    o IPv4 da interface seguido da máscara (dotted '255.255.255.0' ou hex
    '0xffffff00', que é como o ifconfig do macOS escreve)."""
    redes = []
    quad = r"(\d{1,3}(?:\.\d{1,3}){3})"
    for m in re.finditer(quad + r"[^\n]*?(?:\n[^\n]*?)??(?:netmask|mask|m[aá]scara)[^\d\n]*"
                         r"(0x[0-9a-f]{8}|" + quad[1:-1] + ")", texto, re.I):
        ip, mascara = m.group(1), m.group(2)
        if mascara.lower().startswith("0x"):
            mascara = str(ipaddress.IPv4Address(int(mascara, 16)))
        try:
            redes.append(ipaddress.IPv4Interface(f"{ip}/{mascara}"))
        except ValueError:
            continue
    return redes


def interfaces_ipv4():
    """[(ip local, broadcast da rede)] de cada interface IPv4 utilizável."""
    redes = []
    saida = _rodar(["ip", "-j", "-4", "addr", "show"])            # Linux
    if saida:
        try:
            for iface in json.loads(saida):
                for a in iface.get("addr_info", []):
                    redes.append(ipaddress.IPv4Interface(f"{a['local']}/{a['prefixlen']}"))
        except (ValueError, KeyError):
            redes = []
    if not redes:                                                # macOS/BSD e Windows
        redes = _redes_de_texto(_rodar(["ifconfig"]) or _rodar(["ipconfig"]))
    saida = []
    for r in redes:
        # loopback, link-local e /31-/32 (VPN tipo Tailscale) não têm broadcast útil
        if r.ip.is_loopback or r.ip.is_link_local or r.network.prefixlen >= 31:
            continue
        saida.append((str(r.ip), str(r.network.broadcast_address)))
    return saida


def buscar_dongles():
    """Um socket por interface, preso ao IP dela, gritando no broadcast dela;
    mais um solto pros destinos fixos. O dongle responde por unicast ao
    remetente, e o IP de origem da resposta é o endereço certo do painel."""
    sel = selectors.DefaultSelector()
    envios = [(ip, bcast) for ip, bcast in interfaces_ipv4()]
    envios += [("", d) for d in DESTINOS_BROADCAST]
    for origem, destino in envios:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            s.bind((origem, 0))
            s.sendto(PROBE, (destino, PORTA_DESCOBERTA))
        except OSError:
            s.close()
            continue
        s.setblocking(False)
        sel.register(s, selectors.EVENT_READ)

    achados = {}
    limite = time.monotonic() + TIMEOUT_BUSCA
    while time.monotonic() < limite:
        for chave, _ in sel.select(timeout=max(0.05, limite - time.monotonic())):
            try:
                dados, endereco = chave.fileobj.recvfrom(512)
                info = json.loads(dados.decode())
            except (OSError, ValueError, UnicodeDecodeError):
                continue
            if info.get("tipo") == "OPENDONGLE_HELLO_V1":
                achados[endereco[0]] = {"host": info.get("host", "opendongle"),
                                        "id": info.get("id", "")}
    for chave in list(sel.get_map().values()):
        chave.fileobj.close()
    sel.close()
    return [{"ip": ip, **d} for ip, d in sorted(achados.items())]


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/":
            self._html(PAGINA)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/buscar":
            self._json({"achados": buscar_dongles()})
        else:
            self.send_error(404)

    def _html(self, html):
        corpo = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, obj):
        corpo = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)


def main():
    servidor = http.server.ThreadingHTTPServer(("127.0.0.1", PORTA_HTTP), Handler)
    url = f"http://127.0.0.1:{PORTA_HTTP}/"
    threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    print(f"OpenDongle Localizador rodando em {url}")
    print("Deixe esta janela aberta. Ctrl+C pra fechar quando terminar.")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
