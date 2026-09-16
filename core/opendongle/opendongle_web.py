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
import opendongle_audio as aud
import opendongle_bluetooth as bt
import opendongle_engine as eng
import opendongle_sistema as sis

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
.item{{flex-wrap:wrap}}.item .ic{{font-size:1.25em;width:28px;text-align:center}}.item .tx{{flex:1 1 150px;min-width:0}}
.acoes{{display:flex;gap:6px;flex-wrap:wrap;margin-left:auto}}
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
    "geral": ("/geral", "/status", "/senha", "/set-password", "/sair", "/sessoes-encerrar",
              "/sistema", "/restaurar", "/reset", "/hora", "/hora-manual", "/espaco",
              "/espaco-analisar", "/espaco-liberar", "/desempenho", "/processo-encerrar",
              "/hardware", "/atualizacoes", "/atualizacoes-verificar",
              "/atualizacoes-instalar", "/energia"),
    "internet": ("/internet", "/hotspot", "/set-hotspot", "/mode-hotspot", "/wifi",
                 "/modem", "/rede", "/lan", "/firewall", "/fw-set", "/tor", "/remoto",
                 "/confirmar", "/rede-confirmar"),
    "dispositivos": ("/dispositivos", "/bluetooth", "/leds", "/led", "/usb", "/usb-papel"),
    "audio": ("/audio", "/audio-test"),
    "avancadas": ("/avancadas", "/logs", "/diagnostico", "/recursos"),
}
_PREFIXOS_CATEGORIA = (("/bt-", "dispositivos"), ("/modem-", "internet"),
                       ("/fixo-", "internet"), ("/redir-", "internet"),
                       ("/remoto-", "internet"), ("/audio-", "audio"))


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
    r = bt.resumo()   # não sobe o bluetoothd só pra mostrar o status
    bt_badge = ("<span class='badge b-ok'>ligado</span>" if r["ligado"]
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
    ("Conta, senha e sessões", "/senha", "senha admin trocar password login entrar sair sessao usuario conta"),
    ("Data, hora e fuso horário", "/hora", "data hora relogio errada fuso horario ntp automatica"),
    ("Espaço em disco", "/espaco", "espaco disco cheio armazenamento liberar limpar ocupando pesado"),
    ("Desempenho (CPU, RAM e processos)", "/desempenho", "desempenho htop cpu ram memoria processos lento travando encerrar"),
    ("Hardware do dongle", "/hardware", "hardware placa chip emmc imei mac modelo sobre versao kernel desgaste"),
    ("Atualizações do sistema", "/atualizacoes", "atualizar atualizacao update upgrade sistema novo apt"),
    ("Reiniciar ou desligar", "/geral", "reiniciar reboot desligar poweroff"),
    ("Nome do dongle, backup e reset", "/sistema", "hostname nome backup restaurar reset fabrica"),
    ("Aparência (claro e escuro)", "/geral", "tema escuro claro modo noturno aparencia cor"),
    ("Wi-Fi e hotspot", "/hotspot", "wifi hotspot nome da rede senha do wifi ssid ponto de acesso modo"),
    ("Conectar a uma rede Wi-Fi", "/wifi", "conectar wifi cliente rede casa internet"),
    ("Modem 4G e chip", "/modem", "4g chip sim operadora apn sinal modem celular"),
    ("LAN, DHCP e IP fixo", "/rede", "lan dhcp ip fixo reservar aparelhos conectados clientes"),
    ("Firewall e portas", "/firewall", "firewall porta redirecionar abrir ssh bloquear"),
    ("Navegação via Tor", "/tor", "tor anonimo privacidade onion"),
    ("Acesso remoto (Tailscale)", "/remoto", "remoto tailscale vpn acessar de longe exit node"),
    ("Bluetooth", "/bluetooth", "bluetooth parear fone caixa teclado mouse controle conectar visivel"),
    ("Aparelhos USB e porta USB", "/usb", "usb pendrive webcam camera teclado mouse periferico host otg porta"),
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
        {item("🔑", "Conta e senha", "Senha, sair e sessões abertas", "/senha")}
        {item("🕒", "Data e hora", "Hora automática, ajuste manual e fuso", "/hora")}
        {item("🔄", "Atualizações", "Correções e melhorias do sistema", "/atualizacoes")}
      </div>
      <div class='card'><h2>Desempenho e espaço</h2>
        {item("📊", "Status e saúde", "Resumo de CPU, RAM, disco e temperatura", "/status")}
        {item("📈", "Desempenho", "CPU por núcleo, memória e processos ao vivo", "/desempenho")}
        {item("💾", "Espaço em disco", "O que está ocupando e liberar espaço", "/espaco")}
      </div>
      <div class='card'><h2>Este dongle</h2>
        {item("🧩", "Hardware", "Placa, eMMC, rádios, modem e MACs", "/hardware")}
        {item("🛠️", "Nome, backup e reset", "Hostname, backup e configuração de fábrica", "/sistema")}
        <div class='row'>
          <form method='post' action='/energia' onsubmit="return confirm('Reiniciar o dongle agora?')">
            <input type='hidden' name='acao' value='reboot'><button class='sec'>Reiniciar</button></form>
          <form method='post' action='/energia' onsubmit="return confirm('Desligar o dongle? Pra ligar de novo é preciso tirar e recolocar.')">
            <input type='hidden' name='acao' value='poweroff'><button class='sec'>Desligar</button></form>
        </div>
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
        {item("🔵", "Bluetooth", _sub_bt(), "/bluetooth")}
        {item("🔌", "Aparelhos USB", _sub_usb(), "/usb")}
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
    sess = sis.sessoes()["sessoes"]
    linhas = "".join(item("🖥️" if x["tty"] else "🌐", f"{x['usuario']} · {x['servico'] or x['tty']}",
                          " · ".join(v for v in (x["origem"] and f"de {x['origem']}", x["desde"]) if v))
                     for x in sess) or "<p>Nenhuma sessão de SSH ou console aberta.</p>"
    return page(f"""
      <div class='card'>
        <h1>🔑 Conta e senha</h1>
        {item("👤", eng.ADMIN_USER, "Usuário de administração do dongle")}
        {msg(m, 'er' if erro else 'ok')}
      </div>
      <div class='card'>
        <h2>Trocar senha</h2>
        <p>É a senha deste painel e do SSH. Ao trocar, as outras sessões do painel
        são encerradas.</p>
        <form method='post' action='/set-password'>
          <label>Nova senha (mín. 6)</label>
          <input name='senha' type='password' minlength='6' required>
          <button>Trocar senha</button>
        </form>
      </div>
      <div class='card'>
        <h2>Sessões</h2>
        {linhas}
        <div class='row'>
          <form method='post' action='/sair'><button class='sec'>Sair do painel</button></form>
          <form method='post' action='/sessoes-encerrar'
                onsubmit="return confirm('Encerrar todas as sessões do painel em outros aparelhos?')">
            <button class='sec'>Encerrar outras sessões do painel</button></form>
        </div>
      </div>""", "Conta e senha")


def tela_hora(r=None):
    st = sis.hora_status()
    opcoes = "".join(f"<option value='{_e(z)}'{' selected' if z == st['fuso'] else ''}>{_e(rot)}</option>"
                     for z, rot in st["fusos"])
    sinc = ("<span class='badge b-ok'>sincronizada pela internet</span>" if st["sincronizada"]
            else "<span class='badge b-av'>não sincronizada</span>")
    manual = ("" if st["automatica"] else f"""
      <div class='card'>
        <h2>Ajustar manualmente</h2>
        <form method='post' action='/hora-manual'>
          <div class='row'>
            <div><label>Data</label><input type='date' name='data' required></div>
            <div><label>Hora</label><input type='time' name='hora' required></div>
          </div>
          <button>Ajustar</button>
        </form>
      </div>""")
    return page(f"""
      <div class='card'>
        <h1>🕒 Data e hora</h1>
        <p style='font-size:1.4em;color:var(--tx);margin:6px 0'>{_e(st['agora'])}</p>
        {sinc}{_resultado(r)}
        <form method='post' action='/hora'>
          <label style='display:flex;gap:10px;align-items:center'>
            <input type='checkbox' name='automatica' value='1' style='width:auto'
            {'checked' if st['automatica'] else ''}>Acertar a hora automaticamente pela internet</label>
          <label>Fuso horário</label>
          <select name='fuso'>{opcoes}</select>
          <div class='aviso'>Este dongle não tem bateria de relógio: sem internet ao
          ligar, a hora fica errada até sincronizar.</div>
          <button>Salvar</button>
        </form>
      </div>{manual}""", "Data e hora")


def _barra(pct):
    cor = "var(--er)" if pct >= 90 else ("var(--av-tx)" if pct >= 75 else "var(--ac)")
    return (f"<div style='height:8px;border-radius:4px;background:var(--sec);overflow:hidden;"
            f"margin-top:6px'><div style='height:100%;width:{min(pct, 100)}%;background:{cor}'>"
            "</div></div>")


def tela_espaco(r=None):
    st = sis.espaco_status()
    discos = "".join(f"<div style='margin:10px 0'><b>{_e(d['nome'])}</b> "
                     f"<small style='color:var(--mut)'>{d['livre_mb']} MB livres de "
                     f"{d['total_mb']} MB</small>{_barra(d['usado_pct'])}</div>"
                     for d in st["discos"])
    lib = st["liberavel"]
    analise = st["analise"]
    if st["analisando"]:
        pastas = "<p>Analisando… esta página atualiza sozinha.</p>"
    elif analise:
        pastas = "".join(item("📁", x["caminho"], f"{x['mb']} MB") for x in analise["pastas"])
        pastas += (f"<p style='font-size:.8em'>Analisado às "
                   f"{time.strftime('%H:%M', time.localtime(analise['quando']))}.</p>")
    else:
        pastas = "<p>Ainda não analisado.</p>"
    return page(f"""
      {"<meta http-equiv='refresh' content='3'>" if st['analisando'] else ""}
      <div class='card'><h1>💾 Espaço em disco</h1>{discos}{_resultado(r)}</div>
      <div class='card'><h2>O que está ocupando</h2>{pastas}
        <form method='post' action='/espaco-analisar'><button class='sec'>Analisar agora</button></form>
      </div>
      <div class='card'><h2>Liberar espaço</h2>
        {item("📦", "Pacotes baixados do apt", f"{lib['cache_apt_mb']} MB")}
        {item("🗂️", "Logs antigos compactados", f"{lib['logs_antigos_mb']} MB")}
        {item("📜", "Registro do sistema (journal)", f"{lib['journal_mb']} MB, mantém os últimos 8 MB")}
        <form method='post' action='/espaco-liberar'><button>Liberar espaço</button></form>
      </div>""", "Espaço em disco")


def tela_desempenho(r=None):
    return page(f"""
      <div class='card'><h1>📈 Desempenho</h1>{_resultado(r)}
        <p id='carga'>Carregando…</p>
        <div id='nucleos'></div>
      </div>
      <div class='card'><h2>Memória e temperatura</h2><div id='memoria'></div></div>
      <div class='card'><h2>Processos</h2>
        <p style='font-size:.85em'>Atualiza a cada 2 s enquanto esta página estiver aberta.</p>
        <div id='processos'></div>
      </div>
      <script>
      const esc=t=>String(t).replace(/[&<>"']/g,c=>'&#'+c.charCodeAt(0)+';');
      const barra=p=>"<div style='height:8px;border-radius:4px;background:var(--sec);overflow:hidden;margin-top:4px'>"
        +"<div style='height:100%;width:"+Math.min(p||0,100)+"%;background:var(--ac)'></div></div>";
      async function atualiza(){{
        let d; try{{ d=await (await fetch('/api/desempenho',{{cache:'no-store'}})).json(); }}catch(e){{ return; }}
        if(!d.ok) return;
        document.getElementById('carga').textContent='Carga (1, 5, 15 min): '+d.carga.join(' · ');
        document.getElementById('nucleos').innerHTML=d.nucleos.map(n=>
          "<div style='margin:6px 0'><small>"+esc(n.nome)+" · "+(n.pct===null?'…':n.pct+'%')
          +(n.mhz?' · '+n.mhz+' MHz':'')+"</small>"+barra(n.pct)+"</div>").join('');
        let m="<div class='item'><span class='ic'>🧠</span><span class='tx'>RAM<small>"
          +d.ram.disponivel_mb+" MB disponíveis de "+d.ram.total_mb+" MB</small></span></div>";
        if(d.swap.total_mb) m+="<div class='item'><span class='ic'>🗜️</span><span class='tx'>Swap (zram)<small>"
          +d.swap.usado_mb+" MB usados de "+d.swap.total_mb+" MB"
          +(d.zram&&d.zram.dados_mb?" · "+d.zram.dados_mb+" MB comprimidos em "+d.zram.comprimido_mb+" MB":"")
          +"</small></span></div>";
        for(const [k,v] of Object.entries(d.temperaturas)) m+="<div class='item'><span class='ic'>🌡️</span>"
          +"<span class='tx'>"+esc(k)+"<small>"+v+" °C</small></span></div>";
        document.getElementById('memoria').innerHTML=m;
        document.getElementById('processos').innerHTML=d.processos.map(p=>
          "<div class='item'><span class='tx'>"+esc(p.nome)+"<small>PID "+p.pid+" · CPU "
          +(p.cpu===null?'…':p.cpu+'%')+" · "+p.ram_mb+" MB</small></span>"
          +(p.protegido?"":"<form method='post' action='/processo-encerrar' style='margin:0' "
            +"onsubmit=\"return confirm('Encerrar "+esc(p.nome)+"?')\"><input type='hidden' name='pid' value='"+p.pid
            +"'><button class='sec' style='width:auto;margin:0;padding:6px 10px'>Encerrar</button></form>")
          +"</div>").join('');
      }}
      atualiza(); setInterval(()=>{{ if(!document.hidden) atualiza(); }}, 2000);
      </script>""", "Desempenho")


def tela_hardware():
    h = sis.hardware()
    e = h["emmc"]
    return page(f"""
      <div class='card'><h1>🧩 Hardware</h1>
        {item("🔌", h["placa"] or "Placa", f"{h['compativel']} · SoC {h['soc']}")}
        {item("⚙️", f"CPU com {h['cpu']['nucleos']} núcleos",
              f"{min(h['cpu']['mhz'] or [0])}–{max(h['cpu']['mhz'] or [0])} MHz · governor {h['cpu']['governor']}")}
        {item("🧠", "RAM", f"{h['ram_mb']} MB visíveis pro sistema")}
        {item("💽", f"eMMC {e['modelo']}", f"{e['tamanho_gb']} GB · fabricado em {e['fabricado']}")}
        {item("🩺", "Desgaste do eMMC", " / ".join(e['desgaste']) + f" · reservas: {e['reservas']}")}
      </div>
      <div class='card'><h2>Rádios e rede</h2>
        {item("📶", "Wi-Fi", f"driver {h['wifi']['driver']} · MAC {h['wifi']['mac']}")}
        {item("🔵", "Bluetooth", f"MAC {h['bluetooth_mac'] or '—'}")}
        {item("🔗", "Rede USB", f"MAC {h['usb_mac'] or '—'}")}
        {item("📱", "Modem 4G", f"IMEI {h['modem']['imei'] or 'não informado pelo modem'} · firmware {h['modem']['firmware'] or '—'}")}
      </div>
      <div class='card'><h2>Software</h2>
        {item("🐧", h["sistema"], f"kernel {h['kernel']}")}
        {item("⏱️", "Ligado há", h["ligado_ha"])}
      </div>""", "Hardware")


def tela_atualizacoes(r=None):
    st = sis.atualizacoes_status()
    etapa = st.get("etapa")
    quando = (time.strftime("%d/%m %H:%M", time.localtime(st["quando"])) if st.get("quando") else "")
    if st["rodando"]:
        # antes do trabalho gravar o 1º estado, a etapa ainda é a da vez anterior
        estado = (f"<span class='badge b-av'>instalando {st.get('pendentes') or ''} atualização(ões)…</span>"
                  if etapa == "instalando" else "<span class='badge b-av'>procurando atualizações…</span>")
    elif etapa == "verificado":
        estado = (f"<span class='badge b-av'>{st['pendentes']} atualização(ões) disponível(is)</span>"
                  if st["pendentes"] else "<span class='badge b-ok'>sistema em dia</span>")
    elif etapa == "instalado":
        estado = f"<span class='badge b-ok'>{st.get('feitas', 0)} atualização(ões) instalada(s)</span>"
    elif etapa == "erro":
        estado = f"<span class='badge b-er'>{_e(st.get('erro', 'falhou'))}</span>"
    else:
        estado = "<span class='badge b-av'>ainda não verificado</span>"
    pacotes = ", ".join(_e(x) for x in st.get("pacotes", [])) if etapa == "verificado" else ""
    botoes = "" if st["rodando"] else f"""
        <form method='post' action='/atualizacoes-verificar'><button class='sec'>Procurar atualizações</button></form>
        {"<form method='post' action='/atualizacoes-instalar' onsubmit=\"return confirm('Instalar agora? Serviços podem reiniciar e a conexão pode piscar.')\"><button>Instalar atualizações</button></form>" if etapa == "verificado" and st.get("pendentes") else ""}"""
    return page(f"""
      {"<meta http-equiv='refresh' content='4'>" if st['rodando'] else ""}
      <div class='card'><h1>🔄 Atualizações</h1>
        {estado}{_resultado(r)}
        {f"<p style='font-size:.85em'>Última verificação: {quando}</p>" if quando else ""}
        {f"<p style='font-size:.85em'>{pacotes}</p>" if pacotes else ""}
        <div class='aviso'>Precisa de internet. O apt é pesado pra este dongle: chega a
        ~170 MB de RAM (medido) e escreve no eMMC. Serviços atualizados reiniciam e a
        conexão pode piscar. Roda em segundo plano: pode fechar esta página.</div>
        {botoes}
      </div>""", "Atualizações")


def _sub_bt():
    r = bt.resumo()
    if not r["ligado"]:
        return "Desligado"
    return f"Ligado · {r['pareados']} aparelho(s) pareado(s)" if r["pareados"] else "Ligado · nenhum aparelho pareado"


def _sub_usb():
    u = sis.usb_dispositivos()
    if u["papel"] == "device":
        return "Porta ligada a um PC (modo rede USB)"
    return f"{len(u['aparelhos'])} aparelho(s) plugado(s)"


def _form_bt(acao, rotulo, campos=None, classe="sec", confirmar=""):
    ocultos = "".join(f"<input type='hidden' name='{_e(k)}' value='{_e(v)}'>"
                      for k, v in (campos or {}).items())
    js = f" onsubmit=\"return confirm('{confirmar}')\"" if confirmar else ""
    return (f"<form method='post' action='{acao}' style='margin:0'{js}>{ocultos}"
            f"<button class='{classe}' style='width:auto;margin:0;padding:6px 12px'>{_e(rotulo)}</button></form>")


def _cartao_pareamento(p):
    if not p:
        return ""
    etapa, codigo = p.get("etapa"), _e(p.get("codigo", ""))
    if etapa == "confirmar":
        corpo = (f"<p>O aparelho mostra o código <b style='font-size:1.4em'>{codigo}</b>? "
                 "Confira na tela dele e confirme nos dois.</p><div class='row'>"
                 + _form_bt("/bt-responder", "Sim, é esse", {"valor": "sim"}, "")
                 + _form_bt("/bt-responder", "Não", {"valor": "nao"}) + "</div>")
    elif etapa in ("pin", "passkey"):
        dica = "PIN (em geral 0000 ou 1234)" if etapa == "pin" else "Código numérico mostrado no aparelho"
        corpo = (f"<form method='post' action='/bt-responder'><label>{dica}</label>"
                 "<input name='valor' inputmode='numeric' maxlength='16' required autofocus>"
                 "<button>Enviar</button></form>")
    elif etapa == "digitar":
        corpo = f"<p>Digite <b style='font-size:1.4em'>{codigo}</b> no aparelho e aperte Enter.</p>"
    elif etapa == "ok":
        corpo = msg("Pareado e conectado.")
    elif etapa == "erro":
        corpo = msg(p.get("erro") or "Não pareou.", "er")
    else:
        corpo = "<p>Pareando… deixe o aparelho perto e em modo de pareamento.</p>"
    return f"<div class='card'><h2>Pareamento · {_e(p.get('mac', ''))}</h2>{corpo}</div>"


def tela_bluetooth(logado, r=None):
    if not logado:
        return page(f"""
      <div class='card'><h1>🔵 Bluetooth</h1>
        {item("🔵", "Bluetooth", _sub_bt())}
        <p>Entre com a senha de administração pra parear e conectar aparelhos.</p>
        <a class='btn' href='/config'><button>Entrar</button></a>
      </div>""", "Bluetooth")
    est = bt.estado()
    if not est["ok"]:
        return page(f"<div class='card'><h1>🔵 Bluetooth</h1>{msg(est['erro'], 'er')}</div>", "Bluetooth")
    p = est["pareamento"]
    esperando = p and p.get("etapa") in ("iniciando", "digitar")
    atualizar = est["buscando"] or esperando

    def linha(a):
        detalhes = [a["tipo"]]
        if a["conectado"]:
            detalhes.append("conectado")
        if a["bateria"] is not None:
            detalhes.append(f"bateria {a['bateria']}%")
        if a["audio"] and a["pareado"]:
            detalhes.append("áudio pela categoria Áudio")
        if a["pareado"]:
            acoes = (_form_bt("/bt-desconectar", "Desconectar", {"mac": a["mac"]}) if a["conectado"]
                     else _form_bt("/bt-conectar", "Conectar", {"mac": a["mac"]}))
            acoes += _form_bt("/bt-esquecer", "Esquecer", {"mac": a["mac"]},
                              confirmar="Esquecer este aparelho?")
        else:
            acoes = _form_bt("/bt-parear", "Parear", {"mac": a["mac"]}, "")
        return (f"<div class='item'><span class='ic'>{a['emoji']}</span><span class='tx'>{_e(a['nome'])}"
                f"<small>{_e(' · '.join(detalhes))}</small></span>"
                f"<span class='acoes'>{acoes}</span></div>")

    pareados = [a for a in est["aparelhos"] if a["pareado"]]
    novos = [a for a in est["aparelhos"] if not a["pareado"]]
    lista_novos = "".join(linha(a) for a in novos) or "<p>Nenhum aparelho com nome encontrado ainda.</p>"
    if est["sem_nome"]:
        lista_novos += (f"<p style='font-size:.85em'>Mais {est['sem_nome']} aparelho(s) sem nome por perto "
                        "(sensores e beacons), escondidos.</p>")
    return page(f"""
      {"<meta http-equiv='refresh' content='3'>" if atualizar else ""}
      <div class='card'><h1>🔵 Bluetooth</h1>{_resultado(r)}
        <div class='item'><span class='ic'>🔵</span><span class='tx'>Bluetooth
          <small>{"Ligado" if est["ligado"] else "Desligado"} · {_e(est["mac"])}</small></span>
          {_form_bt("/bt-ligar", "Desligar" if est["ligado"] else "Ligar", {"ligar": "0" if est["ligado"] else "1"})}</div>
        <div class='item'><span class='ic'>👁️</span><span class='tx'>Visível pra outros aparelhos
          <small>{"Sim, por 3 minutos" if est["visivel"] else "Não"}</small></span>
          {_form_bt("/bt-visivel", "Ocultar" if est["visivel"] else "Ficar visível", {"ligar": "0" if est["visivel"] else "1"})}</div>
        <form method='post' action='/bt-nome'><label>Nome que os outros aparelhos veem</label>
          <div class='row'><input name='nome' value='{_e(est["nome"])}' maxlength='32' required>
          <button class='sec' style='margin-top:0;flex:0 0 auto;width:auto'>Salvar</button></div></form>
      </div>
      {_cartao_pareamento(p)}
      <div class='card'><h2>Meus aparelhos</h2>
        {"".join(linha(a) for a in pareados) or "<p>Nenhum aparelho pareado.</p>"}
      </div>
      <div class='card'><h2>Aparelhos por perto</h2>
        {"<p>Procurando…</p>" if est["buscando"] else ""}
        {lista_novos}
        {"" if est["buscando"] else "<form method='post' action='/bt-buscar'><button class='sec'>Procurar aparelhos</button></form>"}
        <div class='aviso'>Coloque o aparelho em modo de pareamento antes de procurar. Fones e
        caixas de som pareiam aqui, e o som é configurado na categoria Áudio.</div>
      </div>""", "Bluetooth")


def tela_usb(r=None):
    u = sis.usb_dispositivos()
    host = u["papel"] == "host"
    lista = "".join(item(a["emoji"], a["nome"], f"{a['tipo']} · {a['id']}") for a in u["aparelhos"]) \
        or "<p>Nenhum aparelho USB plugado.</p>"
    return page(f"""
      <div class='card'><h1>🔌 Aparelhos USB</h1>{_resultado(r)}
        {item("🔁", "Papel da porta USB", "Periférico (host): aparelhos USB podem ser plugados" if host
              else "PC (device): o dongle aparece como rede USB no computador")}
        {_form_bt("/usb-papel", "Mudar pra modo PC" if host else "Mudar pra modo periférico",
                  {"papel": "device" if host else "host"},
                  confirmar="Se o dongle estiver ligado num PC, a rede USB cai até voltar ao modo PC ou reiniciar. Continuar?")}
        <div class='aviso'>No boot o dongle escolhe sozinho: PC detectado vira modo PC; senão,
        periférico. No modo periférico ele precisa de energia externa (cabo OTG com alimentação).</div>
      </div>
      <div class='card'><h2>Plugados agora</h2>{lista}</div>""", "Aparelhos USB")


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


def _form_audio(acao, rotulo, campos, classe="sec"):
    ocultos = "".join(f"<input type='hidden' name='{_e(k)}' value='{_e(v)}'>" for k, v in campos.items())
    return (f"<form method='post' action='{acao}' style='margin:0'>{ocultos}"
            f"<button class='{classe}' style='width:auto;margin:0;padding:6px 12px'>{_e(rotulo)}</button></form>")


def _controle_volume(acao, campos, nome, volume, mudo, maximo=100):
    """Slider que envia sozinho ao soltar, mais o botão de mudo."""
    ocultos = "".join(f"<input type='hidden' name='{_e(k)}' value='{_e(v)}'>" for k, v in campos.items())
    return (f"<div class='item'><span class='ic'>{'🔇' if mudo else '🔊'}</span><span class='tx'>{_e(nome)}"
            f"<form method='post' action='{acao}' style='margin:6px 0 0'>{ocultos}"
            f"<input type='range' name='volume' min='0' max='{maximo}' value='{volume or 0}' "
            f"style='padding:0' onchange='this.form.submit()'>"
            f"<small>{volume if volume is not None else '—'}%</small></form></span>"
            f"<span class='acoes'>{_form_audio(acao, 'Ativar som' if mudo else 'Mudo', dict(campos, mudo='0' if mudo else '1'))}"
            f"</span></div>")


def tela_audio(logado, r=None):
    if not logado:
        n = len(aud.placas()["placas"])
        return page(f"""
      <div class='card'><h1>🎧 Áudio</h1>
        {item("🎧", "Placas de som", f"{n} conectada(s)")}
        <p>Entre com a senha de administração pra ajustar o som.</p>
        <a class='btn' href='/config'><button>Entrar</button></a>
      </div>""", "Áudio")
    info = aud.placas()
    placas_html = ""
    for p in info["placas"]:
        padrao = p["id"] == info["padrao"]
        controles = "".join(
            _controle_volume("/audio-ajustar", {"placa": p["id"], "controle": c["nome"]},
                             f"{c['nome']} ({c['tipo']})", c["volume"], c["mudo"])
            for c in p["controles"]) or "<p>Esta placa não tem controle de volume.</p>"
        tem_entrada = any(c["tipo"] == "entrada" for c in p["controles"])
        placas_html += f"""
      <div class='card'><h2>{'🔌 ' if p['usb'] else ''}{_e(p['nome'])}</h2>
        <p style='font-size:.85em;margin:0'>{'Placa padrão' if padrao else 'Não é a padrão'} · id {_e(p['id'])}</p>
        {controles}
        <div class='acoes' style='margin-top:10px;justify-content:flex-start'>
          {_form_audio("/audio-testar", "Tocar som de teste", {"placa": p["id"], "tipo": "saida"})}
          {_form_audio("/audio-testar", "Testar microfone (3 s)", {"placa": p["id"], "tipo": "entrada"}) if tem_entrada else ""}
          {"" if padrao else _form_audio("/audio-padrao", "Usar como padrão", {"placa": p["id"]})}
        </div>
      </div>"""
    if not info["placas"]:
        placas_html = """
      <div class='card'><h2>Placas de som</h2>
        <p>Nenhuma placa de som conectada. Este dongle não tem som próprio: plugue uma placa
        de som USB (modo periférico da porta USB) ou use áudio Bluetooth abaixo.</p>
      </div>"""
    try:
        bt_ligado = conf.carregar()["audio"]["bluetooth"]
    except (ValueError, OSError):
        bt_ligado = False
    if bt_ligado and aud.bt_ativo():
        ap = aud.bt_aparelhos()
        def linha_bt(x, tipo):
            return (_controle_volume("/audio-bt-ajustar", {"no": x["id"]},
                                     f"{x['nome']}{' · padrão' if x['padrao'] else ''}", x["volume"], x["mudo"], 150)
                    + "<div class='acoes' style='justify-content:flex-start;margin:0 0 8px 40px'>"
                    + _form_audio("/audio-bt-testar", "Tocar som de teste" if tipo == "saida" else "Testar microfone",
                                  {"no": x["id"], "tipo": tipo})
                    + ("" if x["padrao"] else _form_audio("/audio-bt-ajustar", "Usar como padrão",
                                                          {"no": x["id"], "padrao": "1"}))
                    + "</div>")
        lista_bt = ("".join(linha_bt(x, "saida") for x in ap["saidas"])
                    + "".join(linha_bt(x, "entrada") for x in ap["entradas"])) \
            or "<p>Nenhum fone ou caixa conectado. Pareie e conecte em Dispositivos › Bluetooth.</p>"
        corpo_bt = f"""{lista_bt}
        {_form_audio("/audio-bt", "Desligar áudio Bluetooth", {"ligar": "0"})}"""
    elif bt_ligado:
        corpo_bt = f"""{msg("Áudio Bluetooth ligado na configuração, mas o PipeWire não está rodando.", "er")}
        {_form_audio("/audio-bt", "Tentar ligar de novo", {"ligar": "1"}, "")}"""
    else:
        corpo_bt = f"""<p>Pra usar fone, caixa de som ou microfone Bluetooth. Liga o PipeWire, que fica
        rodando enquanto estiver ativo (~15 MB de RAM).{"" if aud.bt_instalado() else
        " Na primeira vez o dongle baixa ~50 MB de pacotes: precisa de internet."}</p>
        <form method='post' action='/audio-bt'><input type='hidden' name='ligar' value='1'>
        <button>Ligar áudio Bluetooth</button></form>"""
    return page(f"""
      <div class='card'><h1>🎧 Áudio</h1>{_resultado(r)}</div>{_cartao_tarefa("audio-bt", r)}
      {placas_html}
      <div class='card'><h2>🔵 Áudio Bluetooth</h2>{corpo_bt}</div>""", "Áudio")


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
          <label>Nome do dongle (o painel fica em nome.local)</label>
          <input name='hostname' value='{_e(s['hostname'])}' required>
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


def _cartao_tarefa(nome, r=None):
    """Andamento de uma instalação em segundo plano (Tor, Tailscale, PipeWire).
    O resultado final só aparece se não houver ação mais nova na tela (r)."""
    est = sis.tarefa_estado(nome)
    if not est:
        return ""
    if est["etapa"] == "rodando":
        minutos = int((time.time() - est["quando"]) // 60)
        return ("<meta http-equiv='refresh' content='5'><div class='card'><h2>⏳ Instalando…</h2>"
                f"<p>{_e(est['titulo'])}: baixando e instalando pacotes"
                f"{f' (há {minutos} min)' if minutos else ''}. Esta página atualiza sozinha.</p></div>")
    if r is not None or time.time() - est["quando"] > 300:
        return ""   # há resultado mais novo, ou é antigo: não fica aparecendo
    if est["etapa"] == "ok":
        return f"<div class='card'>{msg(est.get('aviso') or 'Instalado e ligado.')}</div>"
    return f"<div class='card'>{msg(est.get('erro') or 'A instalação falhou.', 'er')}</div>"


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
        {estado}{_resultado(r)}{_cartao_tarefa("tor", r)}
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
        {estado}{_resultado(r)}{_cartao_tarefa("remoto", r)}
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

    def _send_json(self, dados, code=200):
        corpo = json.dumps(dados, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
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
        if path == "/usb":
            return (self._send(tela_usb()) if self._logado()
                    else self._send(tela_login(voltar=path)))
        if path == "/modem":
            return self._send(tela_modem(self._logado()))
        if path == "/audio":
            return self._send(tela_audio(self._logado()))
        if path == "/diagnostico":
            return self._send(tela_diagnostico(self._logado()))
        protegidas = {"/rede": tela_rede, "/firewall": tela_firewall,
                      "/sistema": tela_sistema, "/tor": tela_tor, "/remoto": tela_remoto,
                      "/hotspot": tela_hotspot, "/senha": tela_senha, "/leds": tela_leds,
                      "/avancadas": tela_avancadas, "/recursos": tela_recursos,
                      "/hora": tela_hora, "/espaco": tela_espaco, "/desempenho": tela_desempenho,
                      "/hardware": tela_hardware, "/atualizacoes": tela_atualizacoes}
        if path == "/api/desempenho":
            if not self._logado():
                return self._send_json({"ok": False, "erro": "login"}, 403)
            return self._send_json(sis.desempenho())
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
            return self._send(tela_sistema(eng.sistema_set(f.get("hostname"))))
        if path == "/led":
            return self._send(tela_leds(eng.led_set(
                f.get("led", ""), f.get("gatilho", ""))))
        if path == "/restaurar":
            return self._send(tela_sistema(eng.restaurar(f.get("backup", ""))))
        if path == "/tor":
            if f.get("ligar") == "1" and not os.path.exists("/usr/bin/tor"):
                return self._send(tela_tor(sis.tarefa_iniciar("tor")))
            return self._send(tela_tor(eng.tor_set(f.get("ligar") == "1")))
        if path == "/remoto":
            if f.get("ligar") == "1" and not os.path.exists("/usr/sbin/tailscaled"):
                return self._send(tela_remoto(sis.tarefa_iniciar(
                    "remoto", lan=f.get("lan") == "1", saida=f.get("saida") == "1")))
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
        if path == "/hora":
            return self._send(tela_hora(eng.hora_set(f.get("automatica") == "1", f.get("fuso"))))
        if path == "/hora-manual":
            return self._send(tela_hora(sis.hora_manual(f.get("data"), f.get("hora"))))
        if path == "/espaco-analisar":
            return self._send(tela_espaco(sis.espaco_analisar()))
        if path == "/espaco-liberar":
            return self._send(tela_espaco(sis.espaco_liberar()))
        if path == "/processo-encerrar":
            return self._send(tela_desempenho(sis.encerrar_processo(f.get("pid"))))
        if path in ("/atualizacoes-verificar", "/atualizacoes-instalar"):
            return self._send(tela_atualizacoes(
                sis.atualizacoes_iniciar(path.endswith("instalar"))))
        if path == "/energia":
            r = sis.energia(f.get("acao"))
            return self._send(page(f"<div class='card'><h1>⚡ Energia</h1>{_resultado(r)}</div>",
                                   "Energia"))
        if path == "/sair":
            return self._redir("/", "s=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")
        if path == "/sessoes-encerrar":
            _chave(renovar=True)
            return self._send(tela_senha("As outras sessões do painel foram encerradas."),
                              extra={"Set-Cookie": _cookie_sessao()})
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
        acoes_bt = {"/bt-ligar": lambda: bt.ligar(f.get("ligar") == "1"),
                    "/bt-visivel": lambda: bt.visivel(f.get("ligar") == "1"),
                    "/bt-nome": lambda: bt.renomear(f.get("nome")),
                    "/bt-buscar": bt.buscar,
                    "/bt-parear": lambda: bt.parear(f.get("mac")),
                    "/bt-responder": lambda: bt.responder(f.get("valor")),
                    "/bt-conectar": lambda: bt.conectar(f.get("mac")),
                    "/bt-desconectar": lambda: bt.desconectar(f.get("mac")),
                    "/bt-esquecer": lambda: bt.esquecer(f.get("mac"))}
        if path in acoes_bt:
            r = acoes_bt[path]()
            # tela nova (GET) depois da ação: recarregar não repete o POST, e a
            # mensagem de erro aparece; as de sucesso já estão no próprio estado
            return self._send(tela_bluetooth(True, r if not r["ok"] or path in
                                             ("/bt-nome", "/bt-ligar", "/bt-visivel", "/bt-buscar") else None))
        if path == "/usb-papel":
            return self._send(tela_usb(sis.usb_papel(f.get("papel"))))
        if path == "/modem-reconectar":
            r = eng.modem_reconectar()
            return self._send(tela_modem(True,
                m=(r.get("aviso") if r["ok"] else r["erro"]), erro=not r["ok"]))
        if path == "/modem-set-apn":
            r = eng.modem_set_apn(f.get("mcc_mnc", ""), f.get("apn", ""))
            return self._send(tela_modem(True,
                m=(r.get("aviso") if r["ok"] else r["erro"]), erro=not r["ok"]))
        if path == "/audio-ajustar":
            mudo = {"1": True, "0": False}.get(f.get("mudo"))
            return self._send(tela_audio(True, aud.ajustar(
                f.get("placa"), f.get("controle"),
                None if mudo is not None else f.get("volume"), mudo)))
        if path == "/audio-testar":
            teste = aud.testar_entrada if f.get("tipo") == "entrada" else aud.testar_saida
            return self._send(tela_audio(True, teste(f.get("placa"))))
        if path == "/audio-padrao":
            return self._send(tela_audio(True, eng.audio_placa_padrao(f.get("placa"))))
        if path == "/audio-bt":
            if f.get("ligar") == "1" and not aud.bt_instalado():
                return self._send(tela_audio(True, sis.tarefa_iniciar("audio-bt")))
            return self._send(tela_audio(True, eng.audio_bt_set(f.get("ligar") == "1")))
        if path == "/audio-bt-ajustar":
            mudo = {"1": True, "0": False}.get(f.get("mudo"))
            return self._send(tela_audio(True, aud.bt_ajustar(
                f.get("no"), None if mudo is not None or f.get("padrao") else f.get("volume"),
                mudo, f.get("padrao") == "1")))
        if path == "/audio-bt-testar":
            teste = aud.bt_testar_entrada if f.get("tipo") == "entrada" else aud.bt_testar_saida
            return self._send(tela_audio(True, teste(f.get("no"))))
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
        try:
            # painel dormindo: sem aparelho pareado, o bluetoothd dorme junto
            bt.reconciliar(parar=True)
        except Exception:
            pass


if __name__ == "__main__":
    if "--ativado" in sys.argv:
        servir_ativado()
    else:
        servir()
