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

Por que a busca ainda funciona mesmo com o dongle sem ser o gateway padrão
do PC (ipv4.never-default, ver TROUBLESHOOTING_pt.md): o probe vai também
pro broadcast da sub-rede padrão do OpenDongle (192.168.100.255), não só
pro broadcast geral (255.255.255.255). A rota até essa sub-rede existe
sempre que a interface do dongle tem IP nela, independente de qual
interface é "a rota padrão" — não precisa enumerar interfaces do sistema.
"""
import http.server
import json
import socket
import threading
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
        `${{d.ip}}</a><div class="mut">${{d.host}}</div></div></div>`
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


def buscar_dongles():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(TIMEOUT_BUSCA)
    for destino in DESTINOS_BROADCAST:
        try:
            s.sendto(PROBE, (destino, PORTA_DESCOBERTA))
        except OSError:
            pass

    achados = {}
    fim = TIMEOUT_BUSCA
    import time
    limite = time.time() + fim
    while time.time() < limite:
        try:
            s.settimeout(max(0.05, limite - time.time()))
            dados, endereco = s.recvfrom(512)
        except (socket.timeout, OSError):
            break
        try:
            info = json.loads(dados.decode())
        except (ValueError, UnicodeDecodeError):
            continue
        if info.get("tipo") != "OPENDONGLE_HELLO_V1":
            continue
        achados[endereco[0]] = info.get("host", "opendongle")
    s.close()
    return [{"ip": ip, "host": host} for ip, host in sorted(achados.items())]


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
