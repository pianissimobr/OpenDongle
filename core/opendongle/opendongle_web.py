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

import base64
import hashlib
import hmac
import html
import ipaddress
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opendongle_config as conf
import opendongle_engine as eng
import opendongle_diag as diag

# O painel dorme quando ocioso (processo encerra): nada de estado só em
# memória. Sessão = cookie assinado; diagnóstico = arquivo em /run (tmpfs).
CHAVE_SESSAO = "/etc/opendongle/sessao.key"
VALIDADE_SESSAO = 12 * 3600
DIAG_RUN = "/run/opendongle/diagnostico.json"
FLAG_PRONTO = "/run/opendongle/web-pronto"
OCIOSO = int(os.environ.get("OPENDONGLE_WEB_OCIOSO", "300"))   # segundos


class _CacheDiag(dict):
    """Último diagnóstico por teste; sobrevive ao painel dormir (não ao
    reboot, e nem precisa)."""

    def __init__(self, caminho):
        super().__init__()
        self._caminho = caminho
        try:
            with open(caminho) as f:
                self.update(json.load(f))
        except (OSError, ValueError):
            pass

    def __setitem__(self, chave, valor):
        super().__setitem__(chave, valor)
        try:
            os.makedirs(os.path.dirname(self._caminho), exist_ok=True)
            with open(self._caminho, "w") as f:
                json.dump(dict(self), f, ensure_ascii=False)
        except OSError:
            pass


ULTIMO_DIAG = _CacheDiag(DIAG_RUN)


def _chave(renovar=False):
    if not renovar:
        try:
            with open(CHAVE_SESSAO, "rb") as f:
                chave = f.read()
            if len(chave) >= 32:
                return chave
        except OSError:
            pass
    chave = secrets.token_bytes(32)
    os.makedirs(os.path.dirname(CHAVE_SESSAO), mode=0o700, exist_ok=True)
    fd = os.open(CHAVE_SESSAO + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(chave)
    os.replace(CHAVE_SESSAO + ".tmp", CHAVE_SESSAO)
    return chave


def _nova_sessao():
    carga = f"{int(time.time()) + VALIDADE_SESSAO}.{secrets.token_urlsafe(9)}".encode()
    assinatura = hmac.new(_chave(), carga, hashlib.sha256).digest()
    return (base64.urlsafe_b64encode(carga).decode().rstrip("=") + "." +
            base64.urlsafe_b64encode(assinatura).decode().rstrip("="))


def _sessao_valida(token):
    try:
        carga_b64, assin_b64 = token.split(".", 1)
        carga = base64.urlsafe_b64decode(carga_b64 + "=" * (-len(carga_b64) % 4))
        assinatura = base64.urlsafe_b64decode(assin_b64 + "=" * (-len(assin_b64) % 4))
        esperada = hmac.new(_chave(), carga, hashlib.sha256).digest()
        return (hmac.compare_digest(assinatura, esperada)
                and int(carga.split(b".", 1)[0]) > time.time())
    except (ValueError, TypeError):
        return False


def _cookie_sessao():
    return f"s={_nova_sessao()}; Path=/; HttpOnly; SameSite=Strict; Max-Age={VALIDADE_SESSAO}"


DETECCAO =("/generate_204", "/gen_204", "/hotspot-detect.html",
            "/ncsi.txt", "/connecttest.txt", "/canonical.html")

# ---------- aparência e layout (modelo do Ajustes do Tarsila) ----------
_ESCURO = ("--bg:#0b1220;--card:#151f36;--in:#0b1220;--br:#243050;--tx:#e6ecf7;"
           "--mut:#8ea0c4;--ac:#4f8cff;--ok:#34d399;--er:#f87171;--sec:#26324f;"
           "--av-bg:rgba(251,191,36,.1);--av-br:#a16207;--av-tx:#fcd34d")
_CLARO = ("--bg:#f2f4f8;--card:#ffffff;--in:#f7f8fb;--br:#dde3ee;--tx:#1b2436;"
          "--mut:#5f6c85;--ac:#2f6fe4;--ok:#0f8a5f;--er:#c93c3c;--sec:#e6ebf4;"
          "--av-bg:#fff6dc;--av-br:#e0b13f;--av-tx:#7a5300")

# claro por padrão; escuro se o sistema pedir (auto) ou se o usuário escolher.
# A escolha é um cookie lido no servidor: a página já sai no tema certo, sem
# piscar, e o dongle não guarda nada.
ESTILO = f"""<style>
:root{{{_CLARO}}}
@media (prefers-color-scheme:dark){{:root:not([data-tema=claro]){{{_ESCURO}}}}}
:root[data-tema=escuro]{{{_ESCURO}}}
*{{box-sizing:border-box}}
button,input,select,textarea{{font-family:inherit}}
body{{font-family:system-ui,sans-serif;margin:0;background:var(--bg);color:var(--tx)}}
.topo{{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:10px;
 padding:10px 16px;background:var(--card);border-bottom:1px solid var(--br)}}
.topo a{{color:var(--tx);text-decoration:none;font-weight:700}}
.app{{display:flex;flex-direction:column;gap:14px;max-width:980px;margin:0 auto;padding:14px}}
nav.cat{{display:flex;gap:6px;overflow-x:auto;padding-bottom:2px}}
nav.cat a{{display:flex;align-items:center;gap:8px;padding:8px 12px;border-radius:10px;
 color:var(--tx);text-decoration:none;white-space:nowrap}}
nav.cat a.atual{{background:var(--sec);font-weight:600}}
main{{flex:1;min-width:0;max-width:600px;width:100%}}
@media (min-width:860px){{.app{{flex-direction:row;gap:24px}}
 nav.cat{{flex-direction:column;width:220px;position:sticky;top:70px;align-self:flex-start}}}}
a.volta{{display:inline-block;margin:0 0 10px;color:var(--ac);text-decoration:none}}
.card{{background:var(--card);border:1px solid var(--br);border-radius:16px;
 padding:18px 20px;margin-bottom:14px}}
h1{{font-size:1.35em;margin:0 0 4px}}h2{{font-size:1.05em;margin:0 0 10px}}
p{{color:var(--mut);line-height:1.5}}
label{{display:block;font-size:.85em;color:var(--mut);margin:12px 0 4px}}
input,select,textarea{{width:100%;padding:12px;border-radius:10px;border:1px solid var(--br);
 background:var(--in);color:var(--tx);font-size:1em}}
button{{width:100%;padding:13px;margin-top:16px;border:0;border-radius:10px;
 background:var(--ac);color:#fff;font-size:1em;font-weight:600;cursor:pointer}}
button.sec{{background:var(--sec);color:var(--tx)}}
a.btn{{display:block;text-decoration:none;text-align:center}}
.badge{{display:inline-block;padding:4px 10px;border-radius:20px;font-size:.8em;font-weight:600}}
.b-ok{{background:rgba(52,211,153,.15);color:var(--ok)}}
.b-er{{background:rgba(248,113,113,.15);color:var(--er)}}
.b-av{{background:rgba(251,191,36,.15);color:var(--av-tx)}}
.row{{display:flex;gap:10px}}.row>*{{flex:1}}
.msg{{padding:10px;border-radius:8px;margin-top:12px;font-size:.9em}}
.msg.ok{{background:rgba(52,211,153,.12);color:var(--ok)}}
.msg.er{{background:rgba(248,113,113,.12);color:var(--er)}}
.aviso{{background:var(--av-bg);border:1px solid var(--av-br);border-radius:8px;padding:10px;
 font-size:.85em;color:var(--av-tx);margin-top:12px}}
.stats{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:12px}}
.stat{{background:var(--in);border:1px solid var(--br);border-radius:10px;padding:10px;text-align:center}}
.stat span{{display:block;font-size:.75em;color:var(--mut);margin-bottom:2px}}
.stat b{{display:block;font-size:1.3em}}.stat b.av{{color:var(--av-tx)}}.stat b.er{{color:var(--er)}}
.linha{{display:flex;justify-content:space-between;align-items:center;text-decoration:none;
 color:var(--tx);padding:10px 0;border-bottom:1px solid var(--br)}}.linha:last-child{{border-bottom:none}}
.item{{display:flex;align-items:center;gap:12px;padding:11px 0;border-bottom:1px solid var(--br);
 color:var(--tx);text-decoration:none}}.item:last-child{{border-bottom:none}}
.item .ic{{font-size:1.25em;width:28px;text-align:center}}.item .tx{{flex:1;min-width:0}}
.item small{{display:block;color:var(--mut);margin-top:2px}}.item .seta{{color:var(--mut)}}
.seg{{display:flex;gap:6px}}.seg button{{margin:0;padding:10px;background:var(--sec);color:var(--tx)}}
.seg button.atual{{background:var(--ac);color:#fff}}
</style>"""

# (id, ícone, nome, rota). Ordem fixa: memória espacial vale mais que favoritos.
CATEGORIAS = [("geral", "🖥️", "Geral", "/geral"),
              ("internet", "🌐", "Internet", "/internet"),
              ("dispositivos", "🔌", "Dispositivos", "/dispositivos"),
              ("audio", "🎧", "Áudio", "/audio")]
CAT_AVANCADAS = ("avancadas", "🧰", "Opções avançadas", "/avancadas")
_CAT_POR_ID = {c[0]: c for c in CATEGORIAS + [CAT_AVANCADAS]}

# rota -> categoria (a rota decide onde a página "mora" na barra lateral)
ROTAS_CATEGORIA = {
    "geral": ("/geral", "/status", "/senha", "/set-password", "/sistema", "/restaurar",
              "/reset"),
    "internet": ("/internet", "/hotspot", "/set-hotspot", "/mode-hotspot", "/wifi",
                 "/modem", "/rede", "/lan", "/firewall", "/fw-set", "/tor", "/remoto",
                 "/confirmar", "/rede-confirmar"),
    "dispositivos": ("/dispositivos", "/bluetooth", "/leds", "/led"),
    "audio": ("/audio", "/audio-test"),
    "avancadas": ("/avancadas", "/logs", "/diagnostico", "/recursos"),
}
_PREFIXOS_CATEGORIA = (("/bluetooth-", "dispositivos"), ("/modem-", "internet"),
                       ("/fixo-", "internet"), ("/redir-", "internet"),
                       ("/remoto-", "internet"))


def categoria_da_rota(path):
    for cat, rotas in ROTAS_CATEGORIA.items():
        if path in rotas:
            return cat
    for prefixo, cat in _PREFIXOS_CATEGORIA:
        if path.startswith(prefixo):
            return cat
    return None


# contexto da requisição atual (cada requisição roda na sua thread)
_CTX = threading.local()


def _ctx(nome, padrao=None):
    return getattr(_CTX, nome, padrao)


def _nav():
    atual = _ctx("categoria")
    # escondidas até os 7 toques, mas visíveis se a pessoa já está nelas
    visivel = _ctx("avancadas") or atual == "avancadas"
    cats = CATEGORIAS + ([CAT_AVANCADAS] if visivel else [])
    return "<nav class='cat'>" + "".join(
        f"<a href='{rota}' class='{'atual' if cid == atual else ''}'>"
        f"<span>{ic}</span>{nome}</a>" for cid, ic, nome, rota in cats) + "</nav>"


def page(corpo, titulo="OpenDongle"):
    cat = _CAT_POR_ID.get(_ctx("categoria"))
    volta = ""
    if cat and _ctx("path") != cat[3]:   # página de detalhe: volta pra categoria
        volta = f"<a class='volta' href='{cat[3]}'>‹ {cat[2]}</a>"
    tema = _ctx("tema", "auto")
    return (f"<!doctype html><html lang='pt-br' data-tema='{tema}'><head>"
            f"<meta charset='utf-8'><meta name='viewport' content='width=device-width,"
            f"initial-scale=1'><title>{html.escape(titulo)}</title>{ESTILO}</head><body>"
            f"<div class='topo'><a href='/'>🔌 OpenDongle</a></div>"
            f"<div class='app'>{_nav()}<main>{volta}{corpo}</main></div>"
            f"{SCRIPT_ENVIO}</body></html>").encode()


def item(icone, titulo, sub="", url=None, extra=""):
    """Linha do Tarsila: ícone, título, subtítulo e seta (quando é link)."""
    tag, fim = (f"<a class='item' href='{url}'>", "</a>") if url else ("<div class='item'>", "</div>")
    sub_html = f"<small>{html.escape(sub)}</small>" if sub else ""
    seta = "<span class='seta'>›</span>" if url else extra
    return (f"{tag}<span class='ic'>{icone}</span><span class='tx'>{html.escape(titulo)}"
            f"{sub_html}</span>{seta}{fim}")


# Ao enviar um formulário, a resposta pode demorar (aplicar config, acordar
# o painel): avisa na hora em vez de parecer travado.
SCRIPT_ENVIO = """<div id='carregando' style='display:none;position:fixed;inset:0;
 background:rgba(11,18,32,.7);color:#fff;align-items:center;justify-content:center;
 font:600 1.1em system-ui,sans-serif;z-index:9'>Carregando…</div>
<script>document.addEventListener('submit',function(){
 document.getElementById('carregando').style.display='flex'});
window.addEventListener('pageshow',function(){
 document.getElementById('carregando').style.display='none'});</script>"""


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


def tela_status():
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
        <h1>📊 Status e saúde</h1>
        {badge}
        <p>{linha}</p>
        <p>Modo atual: <b>{modo}</b></p>{ssid}
        <p style='margin-top:16px'>Para acessar este painel a qualquer
        momento, digite <b>opendongle.local</b> (ou {eng.ip_lan()}).</p>
      </div>
      <div class='card'>
        <h2>📊 Saúde do sistema</h2>
        {tiles}
      </div>
      <div class='card'>
        <h2>🧩 Hardware</h2>
        {_resumo_hardware()}
      </div>
      """, "Status e saúde")


# Índice de busca com sinônimos coloquiais (título, rota, palavras).
BUSCA = [
    ("Status e saúde do sistema", "/status", "status saude cpu ram memoria disco temperatura ligado internet"),
    ("Senha de administração", "/senha", "senha admin trocar password login entrar"),
    ("Nome, fuso horário e backup", "/sistema", "hostname nome fuso hora horario backup restaurar reset fabrica"),
    ("Aparência (claro e escuro)", "/geral", "tema escuro claro modo noturno aparencia cor"),
    ("Wi-Fi e hotspot", "/hotspot", "wifi hotspot nome da rede senha do wifi ssid ponto de acesso modo"),
    ("Conectar a uma rede Wi-Fi", "/wifi", "conectar wifi cliente rede casa internet"),
    ("Modem 4G e chip", "/modem", "4g chip sim operadora apn sinal modem celular"),
    ("LAN, DHCP e IP fixo", "/rede", "lan dhcp ip fixo reservar aparelhos conectados clientes"),
    ("Firewall e portas", "/firewall", "firewall porta redirecionar abrir ssh bloquear"),
    ("Navegação via Tor", "/tor", "tor anonimo privacidade onion"),
    ("Acesso remoto (Tailscale)", "/remoto", "remoto tailscale vpn acessar de longe exit node"),
    ("Bluetooth", "/bluetooth", "bluetooth parear fone caixa teclado mouse"),
    ("LEDs", "/leds", "led luz luzes piscar"),
    ("Áudio", "/audio", "audio som fone microfone volume"),
]


def tela_inicio(extra=""):
    st = eng.status()
    badge = ("<span class='badge b-ok'>conectado à internet</span>" if st["internet"]
             else "<span class='badge b-er'>sem internet</span>")
    modo = {"hotspot": "Ponto de acesso (hotspot)", "wifi": "Conectado a um Wi-Fi",
            "indefinido": "Wi-Fi ocioso"}.get(st["modo"], st["modo"])
    indice = json.dumps([{"t": t, "u": u, "p": pal} for t, u, pal in BUSCA],
                        ensure_ascii=False).replace("</", "<\\/")
    cats = CATEGORIAS + ([CAT_AVANCADAS] if _ctx("avancadas") else [])
    return page(f"""
      <div class='card'>
        <input id='busca' type='search' placeholder='🔎 Buscar ajuste (ex.: senha do wifi)'
               autocomplete='off'>
        <div id='resultados'></div>
      </div>
      <div class='card'>
        <h1>🔌 OpenDongle</h1>{badge}
        <p>{_e(modo)}{" · rede " + _e(st['hotspot_ssid']) if st.get('hotspot_ssid') else ""}</p>
        {extra}
        {item("📊", "Status e saúde", "CPU, RAM, disco e temperatura", "/status")}
      </div>
      <div class='card'>
        {"".join(item(ic, nome, "", rota) for _, ic, nome, rota in cats)}
      </div>
      <script>
      (function(){{
        const idx={indice};
        const tira=t=>t.normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase();
        const caixa=document.getElementById('busca'), res=document.getElementById('resultados');
        caixa.addEventListener('input',()=>{{
          const q=tira(caixa.value.trim()); res.innerHTML='';
          if(!q) return;
          idx.filter(x=>q.split(/\\s+/).every(w=>tira(x.t+' '+x.p).includes(w)))
             .slice(0,8).forEach(x=>{{
               const a=document.createElement('a'); a.className='item'; a.href=x.u;
               a.textContent=x.t; res.appendChild(a); }});
          if(!res.children.length) res.innerHTML="<p>Nada encontrado.</p>";
        }});
      }})();
      </script>""", "OpenDongle")


def tela_geral():
    try:
        pretty = next(l.split("=", 1)[1].strip().strip('"') for l in open("/etc/os-release")
                      if l.startswith("PRETTY_NAME="))
    except (OSError, StopIteration):
        pretty = "Debian"
    tema = _ctx("tema", "auto")
    botoes = "".join(f"<button type='button' data-t='{v}' class='{'atual' if v == tema else ''}'>"
                     f"{n}</button>" for v, n in (("auto", "Automático"), ("claro", "Claro"),
                                                  ("escuro", "Escuro")))
    return page(f"""
      <div class='card'><h1>🖥️ Geral</h1>
        {item("📊", "Status e saúde", "CPU, RAM, disco e temperatura", "/status")}
        {item("🔑", "Senha de administração", "A senha deste painel e do SSH", "/senha")}
        {item("🛠️", "Nome, fuso horário e backup", "Hostname, fuso, backup e reset", "/sistema")}
      </div>
      <div class='card'><h2>Aparência do painel</h2>
        <div class='seg' id='tema'>{botoes}</div>
      </div>
      <div class='card'><h2>Sobre</h2>
        <div id='versao'>{item("ℹ️", "OpenDongle", pretty)}</div>
        <p id='dica' style='margin:4px 0 0;font-size:.85em'></p>
      </div>
      <script>
      document.querySelectorAll('#tema [data-t]').forEach(b=>b.onclick=()=>{{
        document.cookie='tema='+b.dataset.t+';path=/;max-age=31536000;samesite=strict';
        document.documentElement.dataset.tema=b.dataset.t;
        document.querySelectorAll('#tema button').forEach(x=>x.classList.toggle('atual',x===b));
      }});
      let toques=0;
      document.getElementById('versao').onclick=()=>{{
        toques++;
        if(toques>=7){{document.cookie='avancadas=1;path=/;max-age=31536000;samesite=strict';
          location.href='/avancadas';}}
        else if(toques>=4){{document.getElementById('dica').textContent=
          'Mais '+(7-toques)+' toques pra liberar as opções avançadas';}}
      }};
      </script>""", "Geral")


def tela_internet():
    try:
        cfg = conf.carregar()
    except (ValueError, OSError):
        cfg = conf.PADRAO
    w = cfg["wifi"]
    modo = (f"Hotspot · {w['hotspot']['ssid']}" if w["modo"] == "hotspot"
            else f"Cliente · {w['cliente']['ssid']}")
    lig = lambda v: "ligado" if v else "desligado"
    return page(f"""
      <div class='card'><h1>🌐 Internet</h1>
        {item("📡", "Wi-Fi e hotspot", modo, "/hotspot")}
        {item("📶", "Conectar a uma rede Wi-Fi", "O hotspot desliga enquanto conectado", "/wifi")}
        {item("📱", "Modem 4G e chip", "Operadora, sinal e APN", "/modem")}
      </div>
      <div class='card'><h2>Rede local</h2>
        {item("🌐", "LAN, DHCP e IP fixo", f"IP do dongle {cfg['lan']['ip']}", "/rede")}
        {item("🧱", "Firewall e portas", f"{len(cfg['firewall']['redirecionamentos'])} redirecionamento(s)", "/firewall")}
      </div>
      <div class='card'><h2>Privacidade e acesso de longe</h2>
        {item("🧅", "Navegação via Tor", lig(cfg['tor']['ativo']), "/tor")}
        {item("🔗", "Acesso remoto (Tailscale)", lig(cfg['remoto']['ativo']), "/remoto")}
      </div>""", "Internet")


def tela_dispositivos():
    return page(f"""
      <div class='card'><h1>🔌 Dispositivos</h1>
        {item("🔵", "Bluetooth", "Parear e conectar aparelhos", "/bluetooth")}
        {item("💡", "LEDs", "O que cada luz do dongle mostra", "/leds")}
      </div>""", "Dispositivos")


def tela_avancadas():
    return page(f"""
      <div class='card'><h1>🧰 Opções avançadas</h1>
        {item("📜", "Logs do sistema", "journalctl por serviço", "/logs")}
        {item("🩺", "Diagnóstico de hardware", "Áudio, Bluetooth, vídeo USB e modem", "/diagnostico")}
        {item("🧮", "Memória por serviço", "RAM de cada serviço (PSS)", "/recursos")}
      </div>
      <div class='card'>
        <button class='sec' type='button' onclick="document.cookie='avancadas=;path=/;max-age=0';
          location.href='/geral'">Ocultar opções avançadas</button>
      </div>""", "Opções avançadas")


def tela_recursos():
    r = eng.recursos()
    linhas = "".join(item("⚙️", s_["unit"], f"{s_['kb'] / 1024:.1f} MB")
                     for s_ in r["servicos"] if s_["kb"] >= 512)
    return page(f"""
      <div class='card'><h1>🧮 Memória por serviço</h1>
        <p>RAM disponível: <b>{r['ram_disponivel_kb'] // 1024} MB</b> de
        {r['ram_total_kb'] // 1024} MB · métrica {_e(r['metrica'])}</p>
        {linhas}
      </div>""", "Memória por serviço")


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
      </div>""")


def tela_login(m="", voltar="/"):
    return page(f"""
      <div class='card'>
        <h1>🔑 Entrar</h1>
        <p>Entre com a senha de administração para continuar.</p>
        <form method='post' action='/login'>
          <input type='hidden' name='voltar' value='{_e(voltar)}'>
          <label>Senha de administração</label>
          <input name='senha' type='password' required autofocus>
          <button>Entrar</button>
        </form>{msg(m,'er')}
      </div>""", "Entrar")


def tela_hotspot(m="", erro=False):
    st = eng.status()
    return page(f"""
      <div class='card'>
        <h1>📡 Wi-Fi e hotspot</h1>
        <p>Modo: <b>{_e(st['modo'])}</b> · Internet:
        <b>{'sim' if st['internet'] else 'não'}</b></p>{msg(m, 'er' if erro else 'ok')}
      </div>
      <div class='card'>
        <h2>Nome e senha do hotspot</h2>
        <form method='post' action='/set-hotspot'>
          <label>Nome da rede (SSID)</label>
          <input name='ssid' value='{_e(st.get('hotspot_ssid') or '')}'
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
        <h2>Modo de operação</h2>
        <div class='row'>
          <form method='post' action='/mode-hotspot'>
            <button class='sec'>Virar hotspot</button></form>
          <a class='btn' href='/wifi'><button class='sec'>Conectar
          Wi-Fi</button></a>
        </div>
      </div>""", "Wi-Fi e hotspot")


def tela_senha(m="", erro=False):
    return page(f"""
      <div class='card'>
        <h1>🔑 Senha de administração</h1>
        <p>É a senha deste painel e do usuário do sistema (SSH). Ao trocar,
        as outras sessões abertas do painel são encerradas.</p>
        {msg(m, 'er' if erro else 'ok')}
        <form method='post' action='/set-password'>
          <label>Nova senha (mín. 6)</label>
          <input name='senha' type='password' minlength='6' required>
          <button>Trocar senha</button>
        </form>
      </div>""", "Senha de administração")


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
      {encontrados_html}""")


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
      {acoes}""")


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
      {acao}""")


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
      {acao}""")


# ---------- rede, firewall e sistema (equivalente ao LuCI) ----------
def _e(v):
    return html.escape(str(v), quote=True)


def _voltar(destino=None):
    return ""   # o topo de cada página já tem "‹ Categoria"


def _resultado(r):
    """Mensagem de um resultado do engine (aviso em verde, erro em vermelho)."""
    if r is None:
        return ""
    return msg(r.get("aviso", "Aplicado.") if r["ok"] else r["erro"],
               "ok" if r["ok"] else "er")


def _botao_post(acao, campos, rotulo):
    ocultos = "".join(f"<input type='hidden' name='{_e(k)}' value='{_e(v)}'>"
                      for k, v in campos.items())
    return (f"<form method='post' action='{acao}' style='margin:0'>{ocultos}"
            f"<button class='sec' style='width:auto;margin:0;padding:6px 12px'>"
            f"{_e(rotulo)}</button></form>")


def tela_rede(r=None):
    cfg = eng.config_show()
    if not cfg["ok"]:
        return page(f"<div class='card'>{msg(cfg['erro'], 'er')}</div>" + _voltar())
    lan = cfg["config"]["lan"]
    dhcp = lan["dhcp"]
    clientes = eng.dhcp_clientes()["clientes"]
    linhas_clientes = "".join(
        f"<div class='linha'><span>{_e(c['nome'] or '(sem nome)')}<br>"
        f"<small style='color:var(--mut)'>{_e(c['ip'])} · {_e(c['mac'])}</small></span>"
        + ("<span class='badge b-ok'>fixo</span>" if c["fixo"] else
           _botao_post("/fixo-add", {"mac": c["mac"], "ip": c["ip"],
                                     "nome": c["nome"] or "aparelho"}, "Fixar IP"))
        + "</div>" for c in clientes) or \
        "<p>Nenhum aparelho com IP emprestado agora.</p>"
    linhas_fixos = "".join(
        f"<div class='linha'><span>{_e(f['nome'])}<br>"
        f"<small style='color:var(--mut)'>{_e(f['ip'])} · {_e(f['mac'])}</small></span>"
        + _botao_post("/fixo-rm", {"mac": f["mac"]}, "Remover") + "</div>"
        for f in dhcp["fixos"]) or "<p>Nenhum IP fixo.</p>"
    return page(f"""
      <div class='card'>
        <h1>🌐 LAN e DHCP</h1>{_resultado(r)}
      </div>
      <div class='card'>
        <h2>Aparelhos conectados</h2>{linhas_clientes}
      </div>
      <div class='card'>
        <h2>IPs fixos</h2>{linhas_fixos}
        <form method='post' action='/fixo-add'>
          <label>MAC (ex: AA:BB:CC:DD:EE:FF)</label><input name='mac' required>
          <label>IP</label><input name='ip' required>
          <label>Nome (letras, números, - e _)</label><input name='nome' required>
          <button>Adicionar IP fixo</button>
        </form>
      </div>
      <div class='card'>
        <h2>Rede local</h2>
        <form method='post' action='/lan'>
          <div class='row'>
            <div><label>IP do dongle</label><input name='ip' value='{_e(lan['ip'])}' required></div>
            <div><label>Prefixo</label><input name='prefixo' value='{_e(lan['prefixo'])}' required></div>
          </div>
          <div class='row'>
            <div><label>DHCP início</label><input name='inicio' value='{_e(dhcp['inicio'])}' required></div>
            <div><label>DHCP fim</label><input name='fim' value='{_e(dhcp['fim'])}' required></div>
          </div>
          <label>Tempo do empréstimo (ex: 12h)</label>
          <input name='lease' value='{_e(dhcp['lease'])}' required>
          <div class='aviso'>Trocar o IP do dongle derruba o acesso atual. Você
          terá 3 minutos pra reconectar e confirmar no endereço novo; senão ele
          volta sozinho ao IP anterior.</div>
          <button>Salvar rede local</button>
        </form>
      </div>{_voltar()}""")


def tela_firewall(r=None):
    cfg = eng.config_show()
    if not cfg["ok"]:
        return page(f"<div class='card'>{msg(cfg['erro'], 'er')}</div>" + _voltar())
    fw = cfg["config"]["firewall"]

    def caixa(nome, texto):
        marcado = " checked" if fw[nome] else ""
        return (f"<label style='display:flex;gap:10px;align-items:center'>"
                f"<input type='checkbox' name='{nome}' value='1' style='width:auto'"
                f"{marcado}>{texto}</label>")
    redir = "".join(
        f"<div class='linha'><span>{_e(x['nome'])}<br><small style='color:var(--mut)'>"
        f"{_e(x['proto'])} {_e(x['porta_externa'])} → {_e(x['ip'])}:{_e(x['porta_interna'])}"
        f"</small></span>" + _botao_post("/redir-rm", {"nome": x["nome"]}, "Remover")
        + "</div>" for x in fw["redirecionamentos"]) or "<p>Nenhum redirecionamento.</p>"
    return page(f"""
      <div class='card'>
        <h1>🧱 Firewall</h1>
        <p>A rede local (USB e hotspot) sempre tem acesso. O 4G fica fechado
        pra conexões de fora, exceto o que você liberar aqui.</p>{_resultado(r)}
      </div>
      <div class='card'>
        <h2>Acesso ao dongle</h2>
        <form method='post' action='/fw-set'>
          {caixa('wifi_cliente_confiavel', 'Confiar na rede Wi-Fi em que o dongle é cliente')}
          {caixa('ssh_pela_wan', 'Liberar SSH (porta 22) pelo 4G')}
          {caixa('painel_pela_wan', 'Liberar este painel (porta 80) pelo 4G')}
          <button>Salvar acesso</button>
        </form>
      </div>
      <div class='card'>
        <h2>Redirecionamento de portas</h2>{redir}
        <form method='post' action='/redir-add'>
          <label>Nome</label><input name='nome' required>
          <div class='row'>
            <div><label>Protocolo</label><select name='proto'>
              <option>tcp</option><option>udp</option></select></div>
            <div><label>Porta externa</label><input name='porta_externa' required></div>
          </div>
          <div class='row'>
            <div><label>IP do aparelho</label><input name='ip' required></div>
            <div><label>Porta interna</label><input name='porta_interna' required></div>
          </div>
          <div class='aviso'>No 4G a operadora costuma usar CGNAT: portas
          redirecionadas só funcionam de fora com IP público.</div>
          <button>Adicionar redirecionamento</button>
        </form>
      </div>{_voltar()}""")


GATILHOS_LED = [("auto", "Automático (OpenDongle)"), ("none", "Apagado"),
                ("default-on", "Aceso"), ("heartbeat", "Batimento"),
                ("activity", "Atividade da CPU"),
                ("netdev:wlan0", "Tráfego do Wi-Fi"), ("netdev:wwan0", "Tráfego do 4G"),
                ("netdev:usb0", "Tráfego da USB")]


def tela_sistema(r=None):
    cfg = eng.config_show()
    if not cfg["ok"]:
        return page(f"<div class='card'>{msg(cfg['erro'], 'er')}"
                    f"{_form_restaurar()}</div>" + _voltar())
    s = cfg["config"]["sistema"]
    return page(f"""
      <div class='card'>
        <h1>🛠️ Sistema</h1>{_resultado(r)}
        <form method='post' action='/sistema'>
          <label>Hostname (o painel fica em hostname.local)</label>
          <input name='hostname' value='{_e(s['hostname'])}' required>
          <label>Fuso horário (ex: America/Sao_Paulo)</label>
          <input name='fuso' value='{_e(s['fuso'])}' required>
          <button>Salvar</button>
        </form>
      </div>
      <div class='card'>
        <h2>💾 Backup</h2>
        <a class='btn' href='/backup.json'><button class='sec'>Baixar backup da
        configuração</button></a>
        <div class='aviso'>O backup contém as senhas do Wi-Fi.</div>
        {_form_restaurar()}
      </div>
      <div class='card'>
        <h2>♻️ Reset de fábrica</h2>
        <form method='post' action='/reset'>
          <label>Digite RESET pra confirmar</label>
          <input name='confirmacao' autocomplete='off' required>
          <div class='aviso'>Volta a config ao padrão: Wi-Fi OpenDongle /
          opendongle, IPs fixos, redirecionamentos e LEDs apagados.</div>
          <button>Voltar à configuração de fábrica</button>
        </form>
      </div>{_voltar()}""")


def tela_leds(r=None):
    cfg = eng.config_show()
    if not cfg["ok"]:
        return page(f"<div class='card'>{msg(cfg['erro'], 'er')}</div>", "LEDs")
    leds = "".join(
        f"<form method='post' action='/led'><input type='hidden' name='led' value='{_e(led)}'>"
        f"<label>{_e(led)}</label><div class='row'><select name='gatilho'>"
        + "".join(f"<option value='{_e(v)}'{' selected' if v == atual else ''}>{_e(t)}</option>"
                  for v, t in GATILHOS_LED)
        + "</select><button class='sec' style='margin-top:0;flex:0 0 auto;width:auto'>"
          "Aplicar</button></div></form>"
        for led, atual in cfg["config"]["sistema"]["leds"].items())
    return page(f"""
      <div class='card'><h1>💡 LEDs</h1>
        <p>No automático, as luzes mostram papel USB, modo do Wi-Fi e internet.</p>
        {_resultado(r)}{leds}
      </div>""", "LEDs")


def _form_restaurar():
    return """
        <form method='post' action='/restaurar'>
          <label>Restaurar: cole o conteúdo do backup</label>
          <textarea name='backup' rows='5' required style='width:100%;padding:12px;
           border-radius:10px;border:1px solid var(--br);background:var(--in);
           color:var(--tx);font-family:monospace'></textarea>
          <button class='sec'>Restaurar backup</button>
        </form>"""


def tela_logs(unidade=""):
    r = eng.logs(unidade)
    opcoes = "".join(f"<option value='{_e(u)}'{' selected' if u == unidade else ''}>"
                     f"{_e(u or 'tudo')}</option>" for u in eng.UNITS_LOG)
    corpo = (f"<pre style='white-space:pre-wrap;font-size:.7em;color:var(--mut);"
             f"max-height:70vh;overflow:auto'>{_e(r['texto'])}</pre>"
             if r["ok"] else msg(r["erro"], "er"))
    return page(f"""
      <div class='card'>
        <h1>📜 Logs</h1>
        <form method='get' action='/logs'><div class='row'>
          <select name='u'>{opcoes}</select>
          <button class='sec' style='margin-top:0;flex:0 0 auto;width:auto'>Ver</button>
        </div></form>
        {corpo}
      </div>{_voltar('/sistema')}""")


def tela_tor(r=None):
    st = eng.tor_status()
    if not st["ativo"]:
        estado = "<span class='badge b-er'>desligado</span>"
    elif not st["rodando"]:
        estado = "<span class='badge b-er'>ligado, mas o Tor não está rodando</span>"
    elif st["progresso"] < 100:
        estado = (f"<span class='badge b-av'>conectando à rede Tor: "
                  f"{st['progresso']}%</span><p>{_e(st['detalhe'])}</p>")
    else:
        estado = "<span class='badge b-ok'>ligado: navegação pela rede Tor</span>"
    botao = ("<input type='hidden' name='ligar' value='0'><button class='sec'>"
             "Desligar navegação via Tor</button>" if st["ativo"] else
             "<input type='hidden' name='ligar' value='1'><button>Ligar navegação "
             "via Tor</button>")
    instalar = "" if st["instalado"] else (
        "<div class='aviso'>Na primeira vez o dongle baixa o Tor (~6 MB): precisa "
        "de internet e leva alguns minutos.</div>")
    return page(f"""
      <div class='card'>
        <h1>🧅 Navegação via Tor</h1>
        {estado}{_resultado(r)}
        <p>Ligado, tudo que os aparelhos conectados ao dongle (hotspot e USB)
        acessam passa pela rede Tor, sem configurar nada neles. O DNS também.</p>
        <div class='aviso'>Enquanto estiver ligado: a navegação fica mais lenta;
        chamadas de vídeo, jogos e outros usos de UDP param de funcionar; IPv6
        fica bloqueado; alguns sites recusam acesso vindo do Tor. Pra anonimato
        de verdade, use também o Tor Browser — o Tor na rede esconde o IP, mas
        não o navegador. Enquanto ligado, o Tor usa ~60 MB de RAM.</div>
        {instalar}
        <form method='post' action='/tor'>{botao}</form>
      </div>
      <div class='card'>
        <a class='btn' href='/tor'><button class='sec'>Atualizar status</button></a>
      </div>{_voltar()}""")


def tela_remoto(r=None):
    st = eng.remoto_status()
    link = (r or {}).get("link_login") or st["link_login"]
    if not link.startswith("https://"):   # vira href: nada de javascript: etc.
        link = ""
    if not st["ativo"]:
        estado = "<span class='badge b-er'>desligado</span>"
    elif st["estado"] == "Running":
        ips = ", ".join(_e(ip) for ip in st["ips"])
        estado = (f"<span class='badge b-ok'>conectado</span>"
                  f"<p>Nome: <b>{_e(st['nome'])}</b><br>IP: <b>{ips}</b><br>De qualquer "
                  f"aparelho na sua conta Tailscale, abra http://{_e(st['ips'][0]) if st['ips'] else ''}"
                  f" pra este painel.</p>")
    elif link:
        estado = (f"<span class='badge b-av'>falta entrar na conta</span>"
                  f"<p><a style='color:var(--ac)' href='{_e(link)}' target='_blank' "
                  f"rel='noopener'>Abrir o login do Tailscale</a></p>")
    else:
        estado = (f"<span class='badge b-av'>{_e(st['estado'])}</span>"
                  "<a class='btn' href='/remoto'><button class='sec'>Atualizar"
                  "</button></a>")

    def caixa(nome, texto):
        marcado = " checked" if st[nome] else ""
        return (f"<label style='display:flex;gap:10px;align-items:center'>"
                f"<input type='checkbox' name='{nome}' value='1' style='width:auto'"
                f"{marcado}>{texto}</label>")
    acoes = ""
    if st["ativo"]:
        acoes = f"""
      <div class='card'>
        <div class='row'>
          <form method='post' action='/remoto-login'><button class='sec'>Gerar link
          de login</button></form>
          <form method='post' action='/remoto-logout'><button class='sec'>Sair da
          conta</button></form>
        </div>
        <form method='post' action='/remoto'><input type='hidden' name='ligar' value='0'>
          <button class='sec'>Desligar acesso remoto</button></form>
      </div>"""
    instalar = "" if st["instalado"] else (
        "<div class='aviso'>Na primeira vez o dongle baixa o Tailscale (~35 MB) do "
        "repositório oficial deles: precisa de internet e leva alguns minutos.</div>")
    return page(f"""
      <div class='card'>
        <h1>🔗 Acesso remoto</h1>
        {estado}{_resultado(r)}
        <p>Com o Tailscale, você acessa este dongle de qualquer lugar, sem abrir
        portas no roteador nem precisar de IP público (funciona até no 4G).</p>
        <form method='post' action='/remoto'>
          <input type='hidden' name='ligar' value='1'>
          {caixa('lan', 'Também acessar os aparelhos conectados ao dongle (LAN)')}
          {caixa('saida', 'Usar a internet do dongle de longe (exit node)')}
          <div class='aviso'>As duas opções acima precisam ser aprovadas no painel de
          admin do Tailscale depois de ligar. Usa ~30 MB de RAM.</div>
          {instalar}
          <button>{'Salvar' if st['ativo'] else 'Ligar acesso remoto'}</button>
        </form>
      </div>{acoes}{_voltar()}""")


def tela_confirmar(r=None):
    return page(f"""
      <div class='card'>
        <h1>✅ Confirmar mudança de rede</h1>
        <p>Se você está vendo esta página, o dongle está acessível no endereço
        novo. Confirme pra manter a mudança; sem confirmação ela é desfeita
        sozinha em até 3 minutos.</p>{_resultado(r)}
        <form method='post' action='/rede-confirmar'><button>Manter a nova
        configuração</button></form>
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
        return any(_sessao_valida(x.strip().removeprefix("s="))
                   for x in c.split(";") if x.strip().startswith("s="))

    def _cookie(self, nome):
        for parte in self.headers.get("Cookie", "").split(";"):
            chave, _, valor = parte.strip().partition("=")
            if chave == nome:
                return valor
        return None

    def _contexto(self, path):
        """Categoria (barra lateral e "‹ voltar"), tema e opções avançadas da
        requisição atual, lidos por page() sem mudar a assinatura das telas."""
        _CTX.path = path
        _CTX.categoria = categoria_da_rota(path)
        tema = self._cookie("tema")
        _CTX.tema = tema if tema in ("auto", "claro", "escuro") else "auto"
        _CTX.avancadas = self._cookie("avancadas") == "1"

    def _form(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        d = urllib.parse.parse_qs(self.rfile.read(n).decode())
        return {k: v[0] for k, v in d.items()}

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        ip = eng.ip_lan()
        if path in DETECCAO:                     # portal cativo
            return self._redir(f"http://{ip}/")
        host = self.headers.get("Host", "").split(":")[0].strip("[]")
        # nome de domínio qualquer = DNS sequestrado pelo portal cativo;
        # IP literal é acesso direto (inclusive pelo IP do dongle na rede
        # de casa, no modo cliente) e não pode ser mandado pra LAN USB
        if host not in ("opendongle.local", "opendongle") and not _eh_ip(host):
            return self._redir(f"http://{ip}/")
        self._contexto(path)
        publicas = {"/": tela_inicio, "/status": tela_status, "/wifi": tela_wifi,
                    "/geral": tela_geral, "/internet": tela_internet,
                    "/dispositivos": tela_dispositivos, "/confirmar": tela_confirmar}
        if path in publicas:
            return self._send(publicas[path]())
        if path == "/config":
            return (self._redir("/") if self._logado()
                    else self._send(tela_login(voltar="/")))
        if path == "/bluetooth":
            return self._send(tela_bluetooth(self._logado()))
        if path == "/modem":
            return self._send(tela_modem(self._logado()))
        if path == "/audio":
            return self._send(tela_audio(self._logado()))
        if path == "/diagnostico":
            return self._send(tela_diagnostico(self._logado()))
        protegidas = {"/rede": tela_rede, "/firewall": tela_firewall,
                      "/sistema": tela_sistema, "/tor": tela_tor, "/remoto": tela_remoto,
                      "/hotspot": tela_hotspot, "/senha": tela_senha, "/leds": tela_leds,
                      "/avancadas": tela_avancadas, "/recursos": tela_recursos}
        if path in protegidas or path in ("/logs", "/backup.json"):
            if not self._logado():
                return self._send(tela_login(voltar=path))
            if path == "/logs":
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                return self._send(tela_logs(q.get("u", [""])[0]))
            if path == "/backup.json":
                return self._enviar_backup()
            return self._send(protegidas[path]())
        return self._redir("/")

    def _enviar_backup(self):
        r = eng.backup()
        if not r["ok"]:
            return self._send(tela_sistema(r))
        corpo = r["backup"].encode()
        nome = f"opendongle-backup-{time.strftime('%Y%m%d-%H%M')}.json"
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Disposition", f"attachment; filename={nome}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        f = self._form()
        self._contexto(path)
        if path == "/login":
            # senha conferida contra /etc/shadow (a mesma do sistema)
            voltar = f.get("voltar") or "/"
            if not voltar.startswith("/") or voltar.startswith("//"):
                voltar = "/"   # só caminho local: nada de redirecionar pra fora
            if _checa_admin(f.get("senha", "")):
                return self._redir(voltar, _cookie_sessao())
            _CTX.categoria = categoria_da_rota(voltar)
            return self._send(tela_login("Senha incorreta.", voltar))
        if path == "/wifi":
            # aceita o SSID digitado manualmente OU o escolhido na lista
            ssid = (f.get("ssid_manual") or "").strip() or \
                   (f.get("ssid_lista") or "").strip() or \
                   (f.get("ssid") or "").strip()
            r = eng.connect_wifi(ssid, f.get("senha", ""))
            if r["ok"]:
                _CTX.categoria = None
                return self._send(tela_inicio(msg("Conectado! " + r.get("aviso", ""))))
            return self._send(tela_wifi(r["erro"]))
        if path == "/rede-confirmar":
            # sem login de propósito: depois de trocar o IP da LAN o cookie
            # da sessão ficou no endereço antigo. Só cancela a reversão de uma
            # mudança que um admin já fez — não altera nada por conta própria.
            return self._send(tela_confirmar(eng.executar("rede-confirmar", {})))
        # daqui: ações protegidas
        if not self._logado():
            return self._redir("/config")
        if path == "/lan":
            return self._send(tela_rede(eng.lan_set(
                f.get("ip"), f.get("prefixo"), f.get("inicio"), f.get("fim"),
                f.get("lease"))))
        if path == "/fixo-add":
            return self._send(tela_rede(eng.dhcp_fixo_add(
                f.get("mac"), f.get("ip"), f.get("nome"))))
        if path == "/fixo-rm":
            return self._send(tela_rede(eng.dhcp_fixo_rm(f.get("mac"))))
        if path == "/fw-set":
            return self._send(tela_firewall(eng.fw_set(
                f.get("wifi_cliente_confiavel") == "1", f.get("ssh_pela_wan") == "1",
                f.get("painel_pela_wan") == "1")))
        if path == "/redir-add":
            return self._send(tela_firewall(eng.fw_redir_add(
                f.get("nome"), f.get("proto"), f.get("porta_externa"), f.get("ip"),
                f.get("porta_interna"))))
        if path == "/redir-rm":
            return self._send(tela_firewall(eng.fw_redir_rm(f.get("nome", ""))))
        if path == "/sistema":
            return self._send(tela_sistema(eng.sistema_set(
                f.get("hostname"), f.get("fuso"))))
        if path == "/led":
            return self._send(tela_leds(eng.led_set(
                f.get("led", ""), f.get("gatilho", ""))))
        if path == "/restaurar":
            return self._send(tela_sistema(eng.restaurar(f.get("backup", ""))))
        if path == "/tor":
            return self._send(tela_tor(eng.tor_set(f.get("ligar") == "1")))
        if path == "/remoto":
            return self._send(tela_remoto(eng.remoto_set(
                f.get("ligar") == "1", f.get("lan") == "1", f.get("saida") == "1")))
        if path == "/remoto-login":
            return self._send(tela_remoto(eng.remoto_login()))
        if path == "/remoto-logout":
            return self._send(tela_remoto(eng.remoto_logout()))
        if path == "/reset":
            if f.get("confirmacao", "").strip() != "RESET":
                return self._send(tela_sistema(
                    {"ok": False, "erro": "Digite RESET (maiúsculas) pra confirmar."}))
            return self._send(tela_sistema(eng.reset()))
        if path == "/set-hotspot":
            r = eng.set_hotspot(f.get("ssid"), f.get("senha"))
            return self._send(tela_hotspot(r.get("aviso") if r["ok"] else r["erro"],
                                           erro=not r["ok"]))
        if path == "/mode-hotspot":
            r = eng.mode_hotspot()
            return self._send(tela_hotspot("Hotspot ativado." if r["ok"] else r["erro"],
                                           erro=not r["ok"]))
        if path == "/set-password":
            r = eng.set_password(f.get("senha", ""))
            if not r["ok"]:
                return self._send(tela_senha(r["erro"], erro=True))
            # senha nova derruba todas as outras sessões; esta ganha uma nova
            _chave(renovar=True)
            return self._send(tela_senha(r.get("aviso")),
                              extra={"Set-Cookie": _cookie_sessao()})
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


def _eh_ip(host):
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


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


class _PainelUnix(ThreadingHTTPServer):
    """Servidor no socket unix que o systemd entrega (fd 3). Encerra sozinho
    depois de OCIOSO segundos sem requisição; o systemd sobe de novo no
    próximo acesso."""
    daemon_threads = True

    def __init__(self, sock):
        super().__init__(None, Painel, bind_and_activate=False)
        self.socket.close()   # o construtor cria um socket TCP que não usamos
        self.socket = sock
        self.ultimo = time.monotonic()

    def get_request(self):
        conexao, _ = self.socket.accept()
        self.ultimo = time.monotonic()
        return conexao, ("unix", 0)   # http.server espera (host, porta)


def servir_ativado():
    if os.environ.get("LISTEN_FDS") != "1":
        sys.exit("Sem socket do systemd (rode via opendongle-web.socket).")
    servidor = _PainelUnix(socket.socket(fileno=3))
    with open(FLAG_PRONTO, "w"):
        pass

    def vigia():
        while time.monotonic() - servidor.ultimo < OCIOSO:
            time.sleep(10)
        servidor.shutdown()
    threading.Thread(target=vigia, daemon=True).start()
    try:
        servidor.serve_forever()
    finally:
        try:
            os.unlink(FLAG_PRONTO)
        except OSError:
            pass


if __name__ == "__main__":
    if "--ativado" in sys.argv:
        servir_ativado()
    else:
        servir()
