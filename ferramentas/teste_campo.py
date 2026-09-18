#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
teste_campo.py — teste de campo do OpenDongle: roteiro manual + logs do dongle
===============================================================================
Roda NO PC. Uma pessoa segue o roteiro (o que tocar no painel, no celular, no
cabo) e o script guarda, pra cada passo, o resultado e os erros que o dongle
registrou naquele intervalo. O objetivo é pegar falhas que só aparecem no uso
real: travamentos, serviços que caem, tracebacks do painel, OOM, mudanças de
modo USB ⇄ tomada. Explicação completa: TESTE_DE_CAMPO.md.

Fluxo (cada comando num terminal; a sessão fica em testes/campo-AAAAMMDD-HHMM):

  python3 ferramentas/teste_campo.py preparar     # dongle no PC pelo USB
  python3 ferramentas/teste_campo.py acompanhar   # 2º terminal: log ao vivo
  python3 ferramentas/teste_campo.py roteiro      # passo a passo (retoma de onde parou)
  python3 ferramentas/teste_campo.py coletar      # baixa os logs e gera relatorio.md
  python3 ferramentas/teste_campo.py encerrar     # tira do dongle o que o preparar pôs

  python3 ferramentas/teste_campo.py roteiro --markdown > CHECKLIST_TESTE_CAMPO.md

Nada fica rodando no dongle além do próprio journal: o `preparar` só faz o
journald gravar em disco a cada 15 s (pra um travamento não levar os últimos
minutos) e liga um timer de 30 s que anota memória/carga/temperatura (a
"sentinela", pra achar a causa de um travamento). O `encerrar` desfaz os dois.

Credenciais: --usuario (padrão user) e a senha em OPENDONGLE_SENHA ou
perguntada. A senha nunca é gravada no disco. Se o roteiro trocar usuário ou
senha, o script pede as novas quando a antiga parar de funcionar.
"""

import argparse
import datetime as dt
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA_TESTES = RAIZ / "testes"
HOSTS_PADRAO = ["192.168.100.1", "opendongle.local"]
TAG_MARCA = "opendongle-teste"
TAG_SENTINELA = "opendongle-sentinela"

JOURNALD_DROPIN = "/etc/systemd/journald.conf.d/90-opendongle-teste.conf"
SENTINELA_SH = "/usr/local/sbin/opendongle-sentinela"
SENTINELA_UNIT = "/etc/systemd/system/opendongle-sentinela"
AUTOSENSE_LOG = "/var/log/usb-role-autosense.log"

# ------------------------------------------------------------------ roteiro
# modo: "usb" (dongle no PC), "tomada" (carregador, sem PC), "qualquer".
# Os ids viram marcadores no log e chaves do relatório: não reaproveite um id.
ROTEIRO = [
    # --- 0. base
    ("base-painel", "Base", "usb", "Abrir o painel pelo USB",
     "Com o dongle no PC, abra http://opendongle.local (ou 192.168.100.1).",
     "A página inicial abre com o estado da internet; se o painel dormia, aparece “Carregando painel” e em seguida a página."),
    ("base-login", "Base", "usb", "Entrar e sair do painel",
     "Entre em Geral › Conta e senha: vai pedir login. Teste uma senha errada e depois a certa. Use “Sair do painel” e entre de novo.",
     "Senha errada mostra erro; a certa entra; depois de sair, as páginas protegidas pedem login outra vez."),
    ("base-tema", "Base", "usb", "Tema claro, escuro e automático",
     "Em Geral › Aparência do painel, alterne Claro, Escuro e Automático e navegue por outras páginas.",
     "O tema muda na hora e continua igual nas outras páginas e depois de recarregar."),
    ("base-busca", "Base", "usb", "Busca da página inicial",
     "Na inicial, busque “senha do wifi”, “bluetooth”, “esqueci a senha” e uma palavra sem sentido.",
     "Resultados relevantes (os com ❓ abrem a resposta na Ajuda); a palavra sem sentido mostra “Nada encontrado”."),
    ("base-avancadas", "Base", "usb", "Liberar opções avançadas (7 toques)",
     "Em Geral › Sobre, toque 7 vezes em “OpenDongle”.",
     "A partir do 4º toque aparece a contagem; no 7º abre Opções avançadas, que passam a aparecer na barra antes da Ajuda."),
    ("base-ajuda", "Base", "qualquer", "Ajuda e FAQ",
     "Abra Ajuda, abra e feche algumas perguntas, use a busca da Ajuda e siga um link de dentro de uma resposta.",
     "Perguntas abrem/fecham; a busca filtra sem se importar com acentos; os links levam à página certa."),
    ("base-dormir", "Base", "qualquer", "Painel dorme e acorda",
     "Feche o painel, espere 6 minutos sem usar e abra de novo.",
     "Aparece “Carregando painel” por alguns segundos e depois a página, sem erro."),
    # --- 1. geral
    ("geral-status", "Geral", "qualquer", "Status e saúde",
     "Abra Geral › Status e saúde e o “Ver tudo”.",
     "CPU, RAM, disco e temperatura com valores plausíveis; hardware (Bluetooth, modem, áudio) com estado."),
    ("geral-desempenho", "Geral", "qualquer", "Desempenho ao vivo",
     "Abra Geral › Desempenho e deixe aberto 1 minuto.",
     "Os números se atualizam sozinhos; a lista de processos aparece; processos essenciais não têm “Encerrar”."),
    ("geral-hora", "Geral", "qualquer", "Data, hora e fuso",
     "Em Geral › Data e hora, troque o fuso, confira a hora, volte ao fuso certo. Desligue a hora automática, ajuste à mão e religue.",
     "A hora mostrada acompanha o fuso; o ajuste manual vale; com internet, religar a automática corrige a hora."),
    ("geral-espaco", "Geral", "qualquer", "Espaço em disco",
     "Em Geral › Espaço em disco, toque em Analisar agora, espere o resultado e depois em Liberar espaço.",
     "A análise termina e lista o que ocupa; liberar informa quantos MB saíram."),
    ("geral-hardware", "Geral", "qualquer", "Hardware",
     "Abra Geral › Hardware.",
     "Placa, eMMC, rádios, modem e MACs preenchidos (sem “None” nem erro)."),
    ("geral-atualizacoes", "Geral", "qualquer", "Procurar atualizações",
     "Com internet, em Geral › Atualizações toque em Procurar atualizações e acompanhe até o fim (não precisa instalar).",
     "A busca roda em segundo plano e termina com a lista ou “nada a atualizar”, sem travar o painel."),
    ("geral-senha", "Geral", "qualquer", "Trocar senha (janela em 2 etapas)",
     "Em Geral › Conta e senha › Trocar senha: teste senha atual errada; depois a certa; na etapa 2 teste senhas diferentes; por fim troque de verdade SEM marcar “Encerrar outras sessões”. Teste o SSH com a senha nova. Volte à senha original do mesmo jeito.",
     "Senha errada e senhas diferentes mostram erro dentro da janela; a troca vale na hora no painel e no SSH; você continua logado. (O script vai pedir a senha nova quando precisar.)"),
    ("geral-senha-outros", "Geral", "qualquer", "Trocar senha derrubando outros aparelhos",
     "Entre no painel também pelo celular. No PC, troque a senha marcando “Encerrar as sessões do painel em outros aparelhos”. Recarregue no celular.",
     "No celular o painel pede login de novo; no PC você continua logado."),
    ("geral-usuario", "Geral", "qualquer", "Trocar nome de usuário",
     "Em Geral › Conta e senha › Trocar nome de usuário, teste um nome inválido (ex.: “Root”) e nomes diferentes nas duas caixas; depois troque de verdade. Entre no SSH com o nome novo. Volte ao nome original.",
     "Erros claros; a troca derruba só as sessões SSH; o painel continua aberto; o SSH aceita o nome novo e recusa o antigo."),
    ("geral-backup", "Geral", "qualquer", "Backup e restauração",
     "Em Geral › Nome, backup e reset: baixe o backup, mude algo simples (ex.: nome do hotspot) e restaure o backup.",
     "O arquivo baixa; a restauração volta a configuração anterior."),
    ("geral-reiniciar", "Geral", "qualquer", "Reiniciar pelo painel",
     "Em Geral, toque em Reiniciar e confirme. Espere voltar e abra o painel.",
     "O dongle volta em 1–2 minutos com tudo funcionando (Wi-Fi, painel, internet)."),
    # --- 2. internet
    ("net-hotspot", "Internet", "qualquer", "Renomear o hotspot",
     "Em Internet › Wi-Fi e hotspot, troque nome e senha do hotspot. Conecte o celular na rede nova.",
     "A rede some e volta com o nome novo; o celular conecta com a senha nova e navega (se houver internet)."),
    ("net-dhcp", "Internet", "qualquer", "Aparelhos conectados e IP fixo",
     "Em Internet › LAN, DHCP e IP fixo, veja o celular na lista, fixe um IP pra ele, desconecte e reconecte o Wi-Fi do celular.",
     "O celular aparece na lista e recebe o IP fixado ao reconectar."),
    ("net-rollback", "Internet", "usb", "Mudança de rede com reversão automática",
     "Em LAN, DHCP e IP fixo, mude o IP do dongle (ex.: 192.168.101.1), salve e NÃO confirme. Espere 3 minutos.",
     "O acesso cai; em até 3 minutos o dongle volta sozinho ao IP anterior e o painel abre em 192.168.100.1."),
    ("net-rollback-confirmar", "Internet", "usb", "Mudança de rede confirmada",
     "Repita a mudança de IP, reconecte (desplugue/plugue o USB se preciso), abra o endereço novo e confirme. Depois volte ao IP original do mesmo jeito.",
     "Com a confirmação a mudança fica; o painel responde no IP novo; a volta ao IP original também funciona."),
    ("net-firewall", "Internet", "qualquer", "Firewall e redirecionamento de porta",
     "Em Internet › Firewall e portas, adicione um redirecionamento qualquer e remova em seguida.",
     "Adiciona e remove sem erro; a internet dos aparelhos continua funcionando."),
    ("net-wifi-cliente", "Internet", "tomada", "Conectar o dongle no Wi-Fi de casa",
     "Com o dongle na tomada, conecte o dongle a uma rede Wi-Fi em Internet › Conectar a uma rede Wi-Fi. Entre na mesma rede com o celular/PC e abra opendongle.local (ou use ferramentas/opendongle_localizar.py).",
     "O dongle conecta, o hotspot some, o LED fica azul e o painel abre pela rede de casa."),
    ("net-voltar-hotspot", "Internet", "tomada", "Voltar ao hotspot",
     "Pelo painel na rede de casa, em Wi-Fi e hotspot toque em Virar hotspot. Conecte o celular no hotspot.",
     "O hotspot volta, o LED fica verde e o celular navega."),
    ("net-4g", "Internet", "tomada", "Internet pelo chip 4G",
     "Com um chip com dados, ligue o dongle na tomada. Conecte o celular no hotspot e navegue. Abra Internet › Modem 4G e chip.",
     "Navega pelo 4G; a página do modem mostra operadora e sinal; Reconectar 4G volta a conectar."),
    ("net-tor", "Internet", "qualquer", "Navegação via Tor",
     "Em Internet › Navegação via Tor, ligue (na 1ª vez instala), acompanhe até terminar e abra check.torproject.org no celular conectado ao dongle. Depois desligue.",
     "A instalação termina sozinha; o site confirma que está usando Tor; ao desligar a navegação volta ao normal."),
    # --- 3. acesso remoto
    ("remoto-tailscale", "Acesso remoto", "qualquer", "Ligar o Tailscale",
     "Em Acesso remoto, ligue (na 1ª vez instala), use o link de login, entre na sua conta e, de outro aparelho na conta Tailscale, abra http://IP-do-tailscale.",
     "Status “conectado” com nome e IP; o painel abre pelo IP do Tailscale."),
    ("remoto-opcoes", "Acesso remoto", "qualquer", "Tailscale: LAN e saída de internet",
     "Marque as opções de LAN e exit node, salve, aprove no admin do Tailscale e teste de outro aparelho.",
     "Com aprovação, o aparelho remoto alcança a LAN do dongle e/ou sai pela internet dele."),
    ("remoto-desligar", "Acesso remoto", "qualquer", "Desligar o Tailscale",
     "Toque em Sair da conta e depois em Desligar acesso remoto.",
     "Status “desligado”; a memória usada volta a cair (Opções avançadas › Memória por serviço)."),
    ("remoto-sessoes", "Acesso remoto", "usb", "Sessões abertas",
     "Abra um SSH no PC (ssh usuario@192.168.100.1) e veja Acesso remoto › Sessões abertas. Toque em Encerrar nessa sessão.",
     "A sessão aparece com a origem; ao encerrar, o SSH cai na hora e some da lista."),
    # --- 4. dispositivos
    ("bt-ligar", "Bluetooth", "qualquer", "Ligar Bluetooth e ficar visível",
     "Em Dispositivos › Bluetooth, ligue, toque em Ficar visível e procure o dongle no celular.",
     "O celular encontra o dongle pelo nome dele; ao Ocultar, some da busca."),
    ("bt-parear", "Bluetooth", "qualquer", "Parear um fone ou caixa",
     "Coloque o fone em modo de pareamento, toque em Procurar aparelhos e depois em Parear no fone. Responda se aparecer código.",
     "O fone aparece na busca com nome; o pareamento conclui e ele fica na lista de pareados."),
    ("bt-audio", "Bluetooth", "qualquer", "Som no fone Bluetooth",
     "Em Áudio, toque em Ligar áudio Bluetooth (na 1ª vez instala e leva minutos). Conecte o fone em Bluetooth e use o teste de som em Áudio.",
     "A instalação termina; o fone aparece como saída e toca o som de teste."),
    ("bt-reconectar", "Bluetooth", "qualquer", "Fone depois de reiniciar",
     "Reinicie o dongle com o fone pareado. Depois toque em Conectar no fone.",
     "O fone continua pareado e conecta de novo sem parear outra vez."),
    ("bt-esquecer", "Bluetooth", "qualquer", "Desconectar e esquecer",
     "Toque em Desconectar e depois em Esquecer. Desligue o áudio Bluetooth em Áudio.",
     "O fone sai da lista; o áudio Bluetooth desliga e a memória volta a cair."),
    ("usb-aparelho", "Dispositivos", "tomada", "Aparelho USB (pendrive ou placa de som)",
     "Com o dongle na tomada e um adaptador OTG, plugue um pendrive ou placa de som. Abra Dispositivos › Aparelhos USB.",
     "O aparelho aparece na lista; a placa de som aparece em Áudio com volume e teste."),
    ("audio-placa", "Áudio", "tomada", "Placa de som USB",
     "Com uma placa de som USB, ajuste volume, mudo e use o teste de som e de microfone.",
     "O volume muda de verdade; o teste toca; o teste de microfone diz se está captando."),
    ("leds", "Dispositivos", "tomada", "Significado das luzes",
     "Observe os LEDs: hotspot com e sem internet, cliente Wi-Fi, e no PC (USB). Compare com Ajuda › luzes.",
     "Verde fixo/piscando no hotspot, azul fixo/piscando no cliente, tudo apagado no PC."),
    # --- 5. primeiro uso e recuperação
    ("cadastro-aparece", "Primeiro uso", "tomada", "Cadastro aparece com a senha de fábrica",
     "Antes: rode `teste_campo.py senha-fabrica` com o dongle no PC (volta a senha pra 1). Ligue na tomada, conecte o celular no hotspot.",
     "O celular abre sozinho (ou ao abrir qualquer site) a tela “Bem-vindo ao seu OpenDongle”; qualquer página do painel leva a ela."),
    ("cadastro-erros", "Primeiro uso", "tomada", "Erros do cadastro",
     "Teste: senha do root “1”, senhas que não batem, nome com número, usuário “root”, senha do usuário igual à do root. Use Voltar e Continuar.",
     "Cada erro aparece na etapa certa sem apagar o que já foi digitado; a sugestão de usuário vem do nome."),
    ("cadastro-concluir", "Primeiro uso", "tomada", "Concluir o cadastro",
     "Preencha tudo certo e conclua. Abra o painel. Em Conta e senha confira usuário e nome.",
     "“Tudo pronto” com o nome; o painel libera já logado; usuário e nome completo aparecem na conta. (O script vai pedir as credenciais novas.)"),
    ("cadastro-usb", "Primeiro uso", "usb", "Cadastro não aparece pelo USB",
     "Volte a senha pra 1 (`teste_campo.py senha-fabrica`), mantenha o dongle no PC e abra o painel.",
     "O painel abre normal, sem cadastro."),
    ("serial-login", "Primeiro uso", "usb", "Console serial pede login e recupera senha",
     "No PC: `sudo screen /dev/ttyACM0 115200`. Tente root com senha errada, depois root com a senha do cadastro e rode `passwd <seu usuário>`.",
     "Pede login (não entra direto); senha errada é recusada; com a do root entra e a troca de senha do usuário funciona."),
    # --- 6. estabilidade
    ("est-tomada-pc", "Estabilidade", "qualquer", "Trocar entre tomada e PC várias vezes",
     "Alterne 3 vezes: tomada (espere o hotspot) → PC (espere o painel pelo USB) → tomada.",
     "Cada troca termina no modo certo, sem travar e sem precisar reiniciar."),
    ("est-uso-longo", "Estabilidade", "tomada", "Uso longo",
     "Deixe o dongle na tomada com um celular navegando/vendo vídeo por 30 minutos ou mais.",
     "Sem quedas nem travamentos; o painel continua abrindo no fim."),
    ("est-memoria", "Estabilidade", "qualquer", "Memória no fim do teste",
     "Abra Opções avançadas › Memória por serviço.",
     "RAM disponível confortável; nada desligado continua ocupando memória (Tor, Tailscale, PipeWire)."),
    ("est-desligar", "Estabilidade", "qualquer", "Desligar pelo painel",
     "Em Geral, toque em Desligar e confirme. Espere 15 s, tire e recoloque.",
     "Desliga (o painel para de responder) e volta normal ao recolocar."),
]
RESULTADOS = {"o": "ok", "f": "falhou", "p": "pulado"}

# ------------------------------------------------------------------ classificação
# Ruído conhecido da imagem (visto num boot normal). Ajuste aqui se aparecer mais.
RUIDO = re.compile("|".join([
    r"RTKit", r"UPower", r"leaked proxy", r"Unknown key 'RequiresMountsFor'",
    r"pam_systemd\(.*\): Failed to release session", r"mm_reap: preauth child terminated",
    r"Failed to get percentage", r"^sudo: .*COMMAND=", r"pam_unix\(sudo:session\)", r"getty@ttyGS0\.service: (State 'stop-sigterm' timed out|Failed with result 'timeout')",
]))
ERRO = re.compile("|".join([
    r"Traceback", r"\bException\b", r"Error:", r"\berror\b", r"\bfailed\b", r"\bFAILED\b",
    r"Failed with result", r"code=exited, status=[1-9]", r"segfault", r"Oops", r"BUG:",
    r"Out of memory", r"oom-kill", r"Killed process", r"earlyoom.*(SIG|kill)", r"Kernel panic",
    r"hung_task", r"blocked for more than", r"I/O error", r"EXT4-fs error", r"watchdog",
    r"\berro\b", r"\bfalhou\b", r"\bFalha\b", r"timed out",
]), re.I)
AVISO = re.compile(r"\bwarn(ing)?\b|\baviso\b|\bretry\b|\breset\b", re.I)


def classificar(prioridade, texto):
    if RUIDO.search(texto):
        return "ruido"
    if (prioridade is not None and prioridade <= 3) or ERRO.search(texto):
        return "erro"
    if (prioridade is not None and prioridade == 4) or AVISO.search(texto):
        return "aviso"
    return "info"


# ------------------------------------------------------------------ sessão
def _agora():
    return dt.datetime.now().astimezone()


def sessao_atual(criar=False):
    PASTA_TESTES.mkdir(exist_ok=True)
    existentes = sorted(p for p in PASTA_TESTES.glob("campo-*") if (p / "sessao.json").exists())
    if criar or not existentes:
        if not criar:
            sys.exit("Nenhuma sessão de teste. Rode primeiro: teste_campo.py preparar")
        pasta = PASTA_TESTES / f"campo-{_agora():%Y%m%d-%H%M}"
        pasta.mkdir(exist_ok=True)
        return pasta
    return existentes[-1]


def ler_json(caminho, padrao):
    try:
        return json.loads(Path(caminho).read_text())
    except (OSError, ValueError):
        return padrao


def gravar_json(caminho, dados):
    tmp = Path(str(caminho) + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2))
    os.replace(tmp, caminho)


# ------------------------------------------------------------------ SSH
class Dongle:
    def __init__(self, hosts, usuario, senha=None, perguntar=True):
        self.hosts = hosts
        self.usuario = usuario
        self.senha = senha if senha is not None else os.environ.get("OPENDONGLE_SENHA")
        self.perguntar = perguntar
        self.host = None
        if not shutil.which("ssh"):
            sys.exit("Falta o ssh no PC.")

    def _base(self, host, lote=True):
        opts = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=5",
                "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=3"]
        if self.senha is not None and shutil.which("sshpass"):
            return (["sshpass", "-e", "ssh", "-o", "PubkeyAuthentication=no"] + opts
                    + [f"{self.usuario}@{host}"])
        return ["ssh"] + (["-o", "BatchMode=yes"] if lote else []) + opts + [f"{self.usuario}@{host}"]

    def _env(self):
        env = dict(os.environ)
        if self.senha is not None:
            env["SSHPASS"] = self.senha
        return env

    def _garante_senha(self):
        if self.senha is None and self.perguntar:
            self.senha = getpass.getpass(f"Senha de {self.usuario} no dongle: ")

    def _nova_credencial(self, host):
        print(f"\n  ⚠ {self.usuario}@{host} recusou a senha (o roteiro trocou usuário ou senha?).")
        novo = input(f"  Usuário [{self.usuario}]: ").strip()
        self.usuario = novo or self.usuario
        self.senha = getpass.getpass("  Senha: ")

    def rodar(self, comando, sudo=False, timeout=30, tentar_credenciais=True):
        """Roda no primeiro host que responder. Devolve (rc, saída) ou (None, motivo)."""
        self._garante_senha()
        final = f"sudo -S -p '' sh -c {sh_quote(comando)}" if sudo else comando
        # nunca None: o ssh herdaria o stdin do terminal e comeria as respostas do roteiro
        entrada = (self.senha + "\n") if sudo and self.senha is not None else ""
        motivo = "sem resposta"
        for host in ([self.host] if self.host else []) + [h for h in self.hosts if h != self.host]:
            try:
                r = subprocess.run(self._base(host) + [final], input=entrada, capture_output=True,
                                   text=True, timeout=timeout, env=self._env())
            except subprocess.TimeoutExpired:
                motivo = f"{host}: tempo esgotado"
                continue
            if _recusado(r):
                if tentar_credenciais and self.perguntar:
                    self._nova_credencial(host)
                    return self.rodar(comando, sudo, timeout, False)
                return None, "senha recusada"
            if r.returncode == 255:
                motivo = f"{host}: {r.stderr.strip()[:80] or 'sem conexão'}"
                continue
            self.host = host
            return r.returncode, r.stdout + (r.stderr if r.returncode else "")
        return None, motivo

    def stream(self, comando, sudo=False):
        """Popen de um comando contínuo (journalctl -f); a senha do sudo vai pelo stdin."""
        self._garante_senha()
        comando_original = comando
        if sudo:
            comando = f"sudo -S -p '' sh -c {sh_quote(comando)}"
        for host in ([self.host] if self.host else []) + [h for h in self.hosts if h != self.host]:
            try:
                teste = subprocess.run(self._base(host) + ["true"], input="", capture_output=True,
                                       text=True, timeout=15, env=self._env())
            except subprocess.TimeoutExpired:
                continue
            if _recusado(teste) and self.perguntar:
                self._nova_credencial(host)
                return self.stream(comando_original, sudo)
            if teste.returncode != 0:
                continue
            self.host = host
            p = subprocess.Popen(self._base(host) + [comando], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                 env=self._env(), bufsize=1)
            if sudo and self.senha is not None:
                p.stdin.write(self.senha + "\n")
                p.stdin.flush()
            p.stdin.close()
            return p
        return None


def _recusado(r):
    # ssh devolve 255 com "Permission denied"; o sshpass devolve 5 pra senha errada
    return r.returncode == 5 or (r.returncode == 255 and "denied" in r.stderr.lower())


def sh_quote(s):
    return "'" + s.replace("'", "'\"'\"'") + "'"


def marcar(dongle, texto):
    """Marcador no journal do dongle (melhor esforço: offline, fica só o horário local)."""
    rc, _ = dongle.rodar(f"logger -t {TAG_MARCA} {sh_quote(texto)}", timeout=8,
                         tentar_credenciais=True)
    return rc == 0


# ------------------------------------------------------------------ comandos
SENTINELA_SCRIPT = r"""#!/bin/sh
# GERADO por ferramentas/teste_campo.py (preparar); removido no encerrar.
m=$(awk '/MemAvailable/{a=$2} /SwapFree/{s=$2} END{print "mem_disp_kb=" a " swap_livre_kb=" s}' /proc/meminfo)
c=$(cut -d' ' -f1-3 /proc/loadavg)
t=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null)
p=$(ps -eo rss=,comm= --sort=-rss | head -3 | awk '{printf "%s:%dMB ", $2, $1/1024}')
r=$(cat /sys/class/usb_role/ci_hdrc.0-role-switch/role 2>/dev/null)
logger -t opendongle-sentinela "$m carga=\"$c\" temp_mc=$t usb=$r maiores=\"$p\""
"""


def cmd_preparar(a):
    pasta = sessao_atual(criar=True)
    d = Dongle(a.host, a.usuario)
    print(f"Sessão: {pasta.relative_to(RAIZ)}")
    rc, saida = d.rodar("date +%s; cat /proc/sys/kernel/random/boot_id; uname -r; "
                        "grep PRETTY_NAME /etc/os-release; id -un; "
                        "cat /sys/class/usb_role/ci_hdrc.0-role-switch/role 2>/dev/null")
    if rc != 0:
        sys.exit(f"Não alcancei o dongle ({saida}). Ligue pelo USB e confira usuário/senha.")
    linhas = saida.splitlines()
    desvio = int(linhas[0]) - int(time.time())
    script = SENTINELA_SCRIPT
    servico = (f"[Unit]\nDescription=OpenDongle teste de campo: sentinela\n[Service]\nType=oneshot\n"
               f"ExecStart={SENTINELA_SH}\n")
    timer = ("[Unit]\nDescription=OpenDongle teste de campo: sentinela a cada 30 s\n[Timer]\n"
             "OnBootSec=20\nOnUnitActiveSec=30\nAccuracySec=5\n[Install]\nWantedBy=timers.target\n")
    journald = ("# GERADO por ferramentas/teste_campo.py: grava o journal a cada 15 s durante\n"
                "# o teste (um travamento não leva os últimos minutos). Removido no encerrar.\n"
                "[Journal]\nStorage=persistent\nSyncIntervalSec=15s\n")
    remoto = (
        f"mkdir -p /etc/systemd/journald.conf.d /var/log/journal && "
        f"printf %s {sh_quote(journald)} > {JOURNALD_DROPIN} && "
        f"printf %s {sh_quote(script)} > {SENTINELA_SH} && chmod 755 {SENTINELA_SH} && "
        f"printf %s {sh_quote(servico)} > {SENTINELA_UNIT}.service && "
        f"printf %s {sh_quote(timer)} > {SENTINELA_UNIT}.timer && "
        f"systemctl daemon-reload && systemctl restart systemd-journald && "
        f"systemctl enable --now opendongle-sentinela.timer >/dev/null 2>&1 && "
        f"systemctl is-active opendongle-sentinela.timer")
    rc, saida_prep = d.rodar(remoto, sudo=True, timeout=60)
    if rc != 0:
        sys.exit(f"Falhou ao preparar o dongle: {saida_prep.strip()[:300]}")
    _, antes = d.rodar("systemctl --failed --no-legend; echo ---; free -m; echo ---; "
                       "opendongle recursos 2>/dev/null | head -40", sudo=True, timeout=60)
    (pasta / "estado-inicial.txt").write_text(antes or "")
    sessao = {"inicio": _agora().isoformat(timespec="seconds"), "inicio_epoch": int(time.time()),
              "hosts": a.host, "usuario": d.usuario, "desvio_relogio_s": desvio,
              "boot_id_inicial": linhas[1] if len(linhas) > 1 else "",
              "kernel": linhas[2] if len(linhas) > 2 else "",
              "sistema": linhas[3].split("=", 1)[-1].strip('"') if len(linhas) > 3 else "",
              "papel_usb_inicial": linhas[5] if len(linhas) > 5 else "",
              "commit_repo": _git("rev-parse", "--short", "HEAD"),
              "repo_sujo": bool(_git("status", "--porcelain"))}
    gravar_json(pasta / "sessao.json", sessao)
    marcar(d, "=== SESSAO INICIO ===")
    print(f"✓ Dongle preparado (sentinela ativa, journal a cada 15 s). Relógio do dongle: "
          f"{desvio:+d} s em relação ao PC.")
    if abs(desvio) > 120:
        print("  ⚠ Relógio muito diferente do PC: a relação passo ⇄ log vai depender dos marcadores.")
    print("Próximos: `acompanhar` num terminal e `roteiro` em outro.")


def _git(*args):
    try:
        return subprocess.run(["git", "-C", str(RAIZ)] + list(args), capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


CORES = {"erro": "\033[31m", "aviso": "\033[33m", "marca": "\033[36;1m", "ruido": "\033[2m",
         "info": "", "sentinela": "\033[2;34m", "conexao": "\033[35;1m"}


def _linha_journal(bruta):
    try:
        j = json.loads(bruta)
    except ValueError:
        return None
    msg = j.get("MESSAGE", "")
    if isinstance(msg, list):   # bytes não-UTF-8
        msg = bytes(msg).decode(errors="replace")
    try:
        prio = int(j.get("PRIORITY"))
    except (TypeError, ValueError):
        prio = None
    quem = j.get("SYSLOG_IDENTIFIER") or j.get("_SYSTEMD_UNIT") or "?"
    ts = int(j.get("__REALTIME_TIMESTAMP", "0")) / 1e6
    if quem == TAG_MARCA:
        tipo = "marca"
    elif quem == TAG_SENTINELA:
        tipo = "sentinela"
    else:
        tipo = classificar(prio, f"{quem}: {msg}")
    return {"ts": ts, "boot": j.get("_BOOT_ID", ""), "quem": quem, "prio": prio, "msg": msg,
            "unidade": j.get("_SYSTEMD_UNIT", ""), "tipo": tipo}


def cmd_acompanhar(a):
    pasta = sessao_atual()
    sessao = ler_json(pasta / "sessao.json", {})
    d = Dongle(sessao.get("hosts") or a.host, a.usuario or sessao.get("usuario", "user"))
    registro = open(pasta / "ao-vivo.log", "a", buffering=1)
    campos = "MESSAGE,PRIORITY,SYSLOG_IDENTIFIER,_SYSTEMD_UNIT,_BOOT_ID"
    online = None
    print("Acompanhando o log do dongle (Ctrl+C pra sair). Ruído conhecido oculto; use --tudo pra ver.",
          flush=True)

    def evento(txt):
        linha = f"{_agora():%H:%M:%S} ▶ {txt}"
        print(f"{CORES['conexao']}{linha}\033[0m", flush=True)
        registro.write(linha + "\n")
    try:
        while True:
            p = d.stream(f"journalctl -f -n 0 -o json --output-fields={campos}", sudo=True)
            if p is None:
                if online is not False:
                    evento("dongle fora de alcance (trocando de modo, reiniciando ou travado?)")
                    online = False
                time.sleep(5)
                continue
            if online is not True:
                evento(f"conectado em {d.usuario}@{d.host}")
                online = True
            for bruta in p.stdout:
                e = _linha_journal(bruta)
                if not e or (e["tipo"] in ("ruido", "info") and not a.tudo) \
                        or (e["tipo"] == "sentinela" and not a.tudo):
                    continue
                hora = dt.datetime.fromtimestamp(e["ts"]).strftime("%H:%M:%S")
                linha = f"{hora} [{e['tipo']:>5}] {e['quem']}: {e['msg']}"
                print(f"{CORES.get(e['tipo'], '')}{linha}\033[0m", flush=True)
                registro.write(linha + "\n")
            evento("conexão com o dongle caiu")
            online = False
            time.sleep(3)
    except KeyboardInterrupt:
        print()


def _markdown():
    saida = ["# Checklist do teste de campo do OpenDongle", "",
             "Gerado por `ferramentas/teste_campo.py roteiro --markdown`. Explicação em "
             "[TESTE_DE_CAMPO.md](TESTE_DE_CAMPO.md). O ideal é seguir pelo script "
             "(`roteiro`), que marca cada passo no log do dongle.", "",
             "Modo: **USB** = dongle ligado no PC · **tomada** = carregador, sem PC · "
             "**qualquer** = tanto faz.", ""]
    grupo = None
    for n, (id_, g, modo, titulo, fazer, esperado) in enumerate(ROTEIRO, 1):
        if g != grupo:
            saida += [f"## {g}", ""]
            grupo = g
        saida += [f"- [ ] **{n}. {titulo}** (`{id_}`, {modo.upper() if modo == 'usb' else modo})",
                  f"  - Fazer: {fazer}", f"  - Esperado: {esperado}", ""]
    return "\n".join(saida)


def cmd_roteiro(a):
    if a.markdown:
        print(_markdown())
        return
    pasta = sessao_atual()
    sessao = ler_json(pasta / "sessao.json", {})
    estado = ler_json(pasta / "roteiro.json", {"passos": {}})
    d = Dongle(sessao.get("hosts") or a.host, a.usuario or sessao.get("usuario", "user"))
    ids = [p[0] for p in ROTEIRO]
    i = next((k for k, pid in enumerate(ids) if pid not in estado["passos"]), len(ids))
    if a.passo:
        if a.passo not in ids:
            sys.exit(f"Passo desconhecido: {a.passo}")
        i = ids.index(a.passo)
    print("Roteiro do teste de campo. Em cada passo: [o]k, [f]alhou, [p]ular, [v]oltar, [s]air.")
    while 0 <= i < len(ROTEIRO):
        id_, grupo, modo, titulo, fazer, esperado = ROTEIRO[i]
        feito = estado["passos"].get(id_)
        print(f"\n\033[1m[{i + 1}/{len(ROTEIRO)}] {grupo} › {titulo}\033[0m  ({id_} · modo {modo})"
              + (f"  — já marcado: {feito['resultado']}" if feito else ""))
        print(f"  Fazer:    {fazer}")
        print(f"  Esperado: {esperado}")
        inicio = time.time()
        marcado = marcar(d, f"PASSO {id_} INICIO")
        if not marcado:
            print("  (dongle fora de alcance: fica só o horário do PC pra este passo)")
        while True:
            r = input("  Resultado [o/f/p/v/s]: ").strip().lower()[:1]
            if r in ("o", "f", "p", "v", "s"):
                break
        if r == "s":
            break
        if r == "v":
            i = max(0, i - 1)
            continue
        nota = ""
        if r == "f":
            nota = input("  O que aconteceu? ").strip()
        elif r in ("o", "p"):
            nota = input("  Observação (Enter pra nenhuma): ").strip()
        fim = time.time()
        marcar(d, f"PASSO {id_} FIM {RESULTADOS[r]}")
        estado["passos"][id_] = {"resultado": RESULTADOS[r], "nota": nota,
                                 "inicio": inicio, "fim": fim, "marcado_no_dongle": marcado,
                                 "usuario_ssh": d.usuario}
        gravar_json(pasta / "roteiro.json", estado)
        if d.usuario != sessao.get("usuario"):
            sessao["usuario"] = d.usuario
            gravar_json(pasta / "sessao.json", sessao)
        i += 1
    feitos = estado["passos"]
    print(f"\n{len(feitos)}/{len(ROTEIRO)} passos marcados · "
          f"{sum(1 for x in feitos.values() if x['resultado'] == 'falhou')} com falha. "
          f"Quando terminar: `coletar`.")


def cmd_senha_fabrica(a):
    d = Dongle(a.host, a.usuario)
    rc, saida = d.rodar(f"echo {sh_quote(d.usuario)}:1 | chpasswd && echo ok", sudo=True)
    if rc != 0:
        sys.exit(f"Não voltou a senha: {saida}")
    print(f"✓ Senha de {d.usuario} voltou pra 1 (o cadastro de primeiro uso aparece na tomada).")


def cmd_coletar(a):
    pasta = sessao_atual()
    sessao = ler_json(pasta / "sessao.json", {})
    roteiro = ler_json(pasta / "roteiro.json", {"passos": {}})
    d = Dongle(sessao.get("hosts") or a.host, a.usuario or sessao.get("usuario", "user"))
    desde = sessao.get("inicio_epoch", int(time.time()) - 86400) + sessao.get("desvio_relogio_s", 0) - 60
    campos = "MESSAGE,PRIORITY,SYSLOG_IDENTIFIER,_SYSTEMD_UNIT,_BOOT_ID"
    print("Baixando o journal da sessão…")
    rc, journal = d.rodar(f"journalctl --since @{desde} -o json --output-fields={campos}",
                          sudo=True, timeout=300)
    if rc is None:
        sys.exit(f"Não alcancei o dongle: {journal}")
    (pasta / "journal.jsonl").write_text(journal)
    extras = {
        "boots.txt": "journalctl --list-boots --no-pager | tail -20",
        "autosense.log": f"tail -n 2000 {AUTOSENSE_LOG}",
        "servicos-falhos.txt": "systemctl --failed --no-legend",
        "recursos-final.txt": "free -m; echo ---; opendongle recursos 2>/dev/null",
        "estado-run.txt": "for f in /run/opendongle/*.json; do echo \"== $f\"; cat \"$f\"; echo; done",
        "config-mascarada.json": "sed -E 's/(\"(senha|psk|chave)[a-z_]*\": *)\"[^\"]*\"/\\1\"***\"/g' "
                                 "/etc/opendongle/config.json",
    }
    for nome, comando in extras.items():
        _, saida = d.rodar(comando, sudo=True, timeout=60)
        (pasta / nome).write_text(saida or "")
    eventos = [e for e in (_linha_journal(l) for l in journal.splitlines()) if e]
    relatorio = gerar_relatorio(sessao, roteiro, eventos, pasta)
    (pasta / "relatorio.md").write_text(relatorio)
    print(f"✓ Relatório: {(pasta / 'relatorio.md').relative_to(RAIZ)}")


def gerar_relatorio(sessao, roteiro, eventos, pasta):
    desvio = sessao.get("desvio_relogio_s", 0)
    passos = roteiro["passos"]
    # janelas de cada passo: pelos marcadores do dongle; sem eles, horário do PC + desvio
    janelas = {}
    for e in eventos:
        if e["tipo"] == "marca":
            m = re.match(r"PASSO (\S+) (INICIO|FIM)", e["msg"])
            if m:
                janelas.setdefault(m.group(1), {})[m.group(2)] = e["ts"]
    for pid, p in passos.items():
        j = janelas.setdefault(pid, {})
        j.setdefault("INICIO", p["inicio"] + desvio)
        j.setdefault("FIM", p["fim"] + desvio)
    for j in janelas.values():   # passo aberto e abandonado (saiu no meio): janela de 5 min
        j.setdefault("FIM", j["INICIO"] + 300)

    def passo_de(ts):
        melhor = None
        for pid, j in janelas.items():
            if j["INICIO"] - 5 <= ts <= j["FIM"] + 30:
                if melhor is None or j["INICIO"] > janelas[melhor]["INICIO"]:
                    melhor = pid
        return melhor

    titulos = {p[0]: (p[1], p[3]) for p in ROTEIRO}
    erros = [e for e in eventos if e["tipo"] in ("erro", "aviso")]
    por_passo = {}
    for e in erros:
        por_passo.setdefault(passo_de(e["ts"]), []).append(e)

    # boots e travamentos: fim de boot sem desligamento limpo, e buracos na sentinela
    boots = []
    for e in eventos:
        if not boots or boots[-1]["id"] != e["boot"]:
            boots.append({"id": e["boot"], "inicio": e["ts"], "fim": e["ts"], "limpo": False})
        boots[-1]["fim"] = e["ts"]
        if re.search(r"Reached target .*(Power-Off|Reboot|System Shutdown|Final Step)|"
                     r"Journal stopped|systemd-shutdown", e["msg"]):
            boots[-1]["limpo"] = True
    buracos = []
    ultimo = {}
    for e in eventos:
        if e["tipo"] == "sentinela":
            anterior = ultimo.get(e["boot"])
            if anterior and e["ts"] - anterior["ts"] > 120:
                buracos.append((anterior, e))
            ultimo[e["boot"]] = e
    memoria = []
    for e in eventos:
        if e["tipo"] == "sentinela":
            m = re.search(r"mem_disp_kb=(\d+)", e["msg"])
            if m:
                memoria.append((int(m.group(1)), e))

    hora = lambda ts: dt.datetime.fromtimestamp(ts).strftime("%d/%m %H:%M:%S")
    linha_ev = lambda e: f"    {hora(e['ts'])} [{e['tipo']}] {e['quem']}: {e['msg'][:300]}"
    falhas = [(pid, p) for pid, p in passos.items() if p["resultado"] == "falhou"]
    L = [f"# Relatório do teste de campo — {pasta.name}", "",
         f"- Início: {sessao.get('inicio', '?')} · commit do repositório: "
         f"`{sessao.get('commit_repo', '?')}`{' (com mudanças locais)' if sessao.get('repo_sujo') else ''}",
         f"- Dongle: {sessao.get('sistema', '?')} · kernel {sessao.get('kernel', '?')} · "
         f"relógio {desvio:+d} s em relação ao PC",
         f"- Passos: {len(passos)}/{len(ROTEIRO)} marcados · "
         f"{sum(1 for p in passos.values() if p['resultado'] == 'ok')} ok · {len(falhas)} com falha · "
         f"{sum(1 for p in passos.values() if p['resultado'] == 'pulado')} pulados",
         f"- Log: {len(eventos)} linhas · {sum(1 for e in erros if e['tipo'] == 'erro')} erros · "
         f"{sum(1 for e in erros if e['tipo'] == 'aviso')} avisos (ruído conhecido já filtrado)",
         f"- Boots na sessão: {len(boots)} · terminados sem desligamento limpo: "
         f"{sum(1 for b in boots[:-1] if not b['limpo'])} (tirar da tomada também conta)",
         ""]
    if memoria:
        menor = min(memoria, key=lambda x: x[0])
        L.append(f"- Menor RAM disponível: {menor[0] // 1024} MB em {hora(menor[1]['ts'])} "
                 f"(passo: {passo_de(menor[1]['ts']) or '—'}) · {menor[1]['msg']}")
        L.append("")

    L += ["## Falhas apontadas no roteiro", ""]
    if not falhas:
        L.append("Nenhuma.")
    for pid, p in falhas:
        g, t = titulos.get(pid, ("?", pid))
        L += [f"### ❌ {g} › {t} (`{pid}`)", "", f"**O que a pessoa viu:** {p['nota'] or '(sem descrição)'}", ""]
        evs = por_passo.get(pid, [])
        L += (["Erros e avisos no log durante o passo:", "", "```"] + [linha_ev(e) for e in evs[:60]]
              + ["```", ""]) if evs else ["Nenhum erro no log durante o passo (problema de interface/UX ou fora do log).", ""]

    L += ["## Erros no log em passos marcados como ok ou pulados", ""]
    silenciosos = [(pid, evs) for pid, evs in por_passo.items()
                   if pid and passos.get(pid, {}).get("resultado") != "falhou"
                   and any(e["tipo"] == "erro" for e in evs)]
    if not silenciosos:
        L.append("Nenhum.")
    for pid, evs in silenciosos:
        g, t = titulos.get(pid, ("?", pid))
        estado = passos[pid]["resultado"] if pid in passos else "sem resultado (abandonado no meio)"
        L += [f"### ⚠ {g} › {t} (`{pid}`, marcado {estado})", "", "```"]
        L += [linha_ev(e) for e in evs if e["tipo"] == "erro"][:40] + ["```", ""]

    L += ["## Erros fora de qualquer passo", ""]
    soltos = [e for e in por_passo.get(None, []) if e["tipo"] == "erro"]
    L += (["```"] + [linha_ev(e) for e in soltos[:80]] + ["```"]) if soltos else ["Nenhum."]
    L.append("")

    L += ["## Travamentos e reinícios", ""]
    if not buracos and all(b["limpo"] for b in boots[:-1]):
        L.append("Nenhum buraco na sentinela e todos os boots terminaram limpos.")
    for antes, depois in buracos:
        L.append(f"- Sentinela parou por {int(depois['ts'] - antes['ts'])} s entre {hora(antes['ts'])} e "
                 f"{hora(depois['ts'])} (passo: {passo_de(antes['ts']) or '—'}). Última leitura: {antes['msg']}")
    for b in boots[:-1]:
        if not b["limpo"]:
            L.append(f"- Boot `{b['id'][:8]}` terminou sem desligamento limpo em {hora(b['fim'])} "
                     f"(passo: {passo_de(b['fim']) or '—'}): tirado da tomada, travou ou reiniciou à força.")
    L += ["", "## Observações dos passos ok/pulados", ""]
    obs = [(pid, p) for pid, p in passos.items() if p["resultado"] != "falhou" and p["nota"]]
    L += [f"- `{pid}` ({p['resultado']}): {p['nota']}" for pid, p in obs] or ["Nenhuma."]
    L += ["", "## Passos não feitos", ""]
    L += [f"- `{p[0]}` — {p[1]} › {p[3]}" for p in ROTEIRO if p[0] not in passos] or ["Nenhum."]
    L += ["", "Arquivos brutos nesta pasta: `journal.jsonl`, `ao-vivo.log`, `autosense.log`, "
          "`servicos-falhos.txt`, `recursos-final.txt`, `estado-inicial.txt`, `estado-run.txt`, "
          "`config-mascarada.json`, `roteiro.json`.", ""]
    return "\n".join(L)


def cmd_encerrar(a):
    pasta = sessao_atual()
    sessao = ler_json(pasta / "sessao.json", {})
    d = Dongle(sessao.get("hosts") or a.host, a.usuario or sessao.get("usuario", "user"))
    marcar(d, "=== SESSAO FIM ===")
    rc, saida = d.rodar(
        f"systemctl disable --now opendongle-sentinela.timer >/dev/null 2>&1; "
        f"rm -f {SENTINELA_UNIT}.service {SENTINELA_UNIT}.timer {SENTINELA_SH} {JOURNALD_DROPIN}; "
        f"systemctl daemon-reload && systemctl restart systemd-journald && echo ok", sudo=True, timeout=60)
    if rc != 0:
        sys.exit(f"Não consegui limpar o dongle: {saida}")
    print("✓ Sentinela e ajuste do journal removidos do dongle. Rode `coletar` antes, se ainda não rodou.")


def main():
    ap = argparse.ArgumentParser(description="Teste de campo do OpenDongle (veja TESTE_DE_CAMPO.md)")
    ap.add_argument("--host", action="append", help="endereço do dongle (repetível); padrão: "
                                                    + ", ".join(HOSTS_PADRAO))
    ap.add_argument("--usuario", help="usuário SSH (padrão: user, ou o último da sessão)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("preparar", help="cria a sessão e prepara o dongle (USB)")
    p = sub.add_parser("acompanhar", help="log ao vivo, reconectando sozinho")
    p.add_argument("--tudo", action="store_true", help="mostra também info, ruído e sentinela")
    p = sub.add_parser("roteiro", help="checklist interativo (retoma de onde parou)")
    p.add_argument("--markdown", action="store_true", help="só imprime o checklist em Markdown")
    p.add_argument("--passo", help="começa por este id")
    sub.add_parser("coletar", help="baixa logs e gera relatorio.md")
    sub.add_parser("encerrar", help="remove sentinela e ajuste do journal do dongle")
    sub.add_parser("senha-fabrica", help="volta a senha do usuário pra 1 (testar o cadastro)")
    a = ap.parse_args()
    a.host = a.host or HOSTS_PADRAO
    if a.cmd in ("preparar", "senha-fabrica"):
        a.usuario = a.usuario or "user"
    {"preparar": cmd_preparar, "acompanhar": cmd_acompanhar, "roteiro": cmd_roteiro,
     "coletar": cmd_coletar, "encerrar": cmd_encerrar, "senha-fabrica": cmd_senha_fabrica}[a.cmd](a)


if __name__ == "__main__":
    main()
