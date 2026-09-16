#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opendongle_ajuda.py — perguntas frequentes do painel (seção Ajuda)
===================================================================
Só dados: o painel monta a página e o índice de busca a partir daqui.
Respostas em HTML simples e fixo (nada vindo de fora); {ip}, {ssid} e
{senha_wifi} são trocados na hora de mostrar.

Cada pergunta: (id, pergunta, resposta, palavras de busca). O id vira a
âncora /ajuda#id, então não mude um id que já existe (links e busca usam).
"""

FAQ = [
    ("Primeiros passos", [
        ("abrir-painel", "Como abro este painel?",
         "Conecte o celular ou o computador ao Wi-Fi do dongle (ou ligue o dongle no "
         "computador pelo cabo USB) e abra <b>opendongle.local</b> no navegador. Se não "
         "abrir, use o endereço <b>{ip}</b>. No celular, a página costuma abrir sozinha "
         "logo depois de conectar no Wi-Fi.",
         "abrir entrar acessar painel endereco site pagina navegador"),
        ("wifi-padrao", "Qual é o nome e a senha do Wi-Fi do dongle?",
         "De fábrica, a rede se chama <b>{ssid}</b> e a senha é <b>{senha_wifi}</b>. "
         "Troque os dois em <a href='/hotspot'>Internet › Wi-Fi e hotspot</a>. Depois de "
         "salvar, conecte de novo na rede com o nome e a senha novos.",
         "nome senha wifi rede hotspot padrao fabrica ssid"),
        ("painel-demora", "Por que o painel demora alguns segundos pra abrir?",
         "Pra sobrar memória pra internet, o painel <b>dorme</b> depois de 5 minutos sem "
         "uso. Na próxima visita ele acorda sozinho e mostra “Carregando painel” enquanto "
         "isso. É normal e não afeta a internet, que continua funcionando o tempo todo.",
         "demora lento carregando painel dormindo abrir"),
        ("pc-ou-tomada", "Qual a diferença entre ligar no computador e na tomada?",
         "<b>No computador</b>, o dongle aparece como uma placa de rede, as luzes ficam "
         "apagadas e o chip 4G não é usado. <b>Na tomada</b> (ou num carregador), o "
         "dongle funciona sozinho: conecta no 4G, liga o Wi-Fi e a porta USB aceita "
         "aparelhos como pendrive, placa de som ou teclado (com um adaptador OTG).",
         "computador pc tomada carregador usb modo host device diferenca"),
    ]),
    ("Internet e Wi-Fi", [
        ("chip-4g", "Coloquei o chip e não tenho internet. O que faço?",
         "Coloque o chip com o dongle desligado. Ao ligar na tomada, a operadora é "
         "reconhecida pelo chip e a conexão é configurada sozinha. Se não conectar, abra "
         "<a href='/modem'>Internet › Modem 4G e chip</a>: lá aparecem o sinal e a "
         "operadora, há o botão <b>Reconectar 4G</b> e dá pra informar o APN à mão "
         "(ele vem nos dados da operadora). Confira também se o chip tem crédito ou "
         "pacote de dados. Ligado no computador, o 4G não é usado.",
         "chip 4g sim operadora sem internet apn sinal dados movel"),
        ("wifi-casa", "Como conecto o dongle no Wi-Fi de casa?",
         "Em <a href='/wifi'>Internet › Conectar a uma rede Wi-Fi</a>, escolha a rede e "
         "digite a senha. Enquanto estiver conectado, o Wi-Fi do próprio dongle "
         "(hotspot) fica desligado: o chip de Wi-Fi não faz os dois ao mesmo tempo. Pra "
         "voltar a abrir o painel, entre na mesma rede de casa e use "
         "<b>opendongle.local</b>. No computador, a ferramenta "
         "<b>opendongle_localizar.py</b> acha o dongle na rede.",
         "wifi casa conectar rede cliente roteador"),
        ("voltar-hotspot", "Como volto a ter o Wi-Fi do dongle (hotspot)?",
         "Em <a href='/hotspot'>Internet › Wi-Fi e hotspot</a>, toque em <b>Virar "
         "hotspot</b>. Se você não consegue mais abrir o painel, ligue o dongle no "
         "computador pelo cabo USB, abra <b>192.168.100.1</b> e faça por lá.",
         "voltar hotspot wifi do dongle sumiu rede sumiu"),
        ("perdi-acesso", "Mudei uma configuração de rede e perdi o acesso. E agora?",
         "Ao mudar o endereço da rede local, o dongle espera você confirmar que ainda "
         "consegue abrir o painel no endereço novo. Sem confirmação, ele "
         "<b>desfaz a mudança sozinho em até 3 minutos</b>. É só esperar e reconectar. "
         "Em último caso, o cabo USB no computador sempre dá acesso por "
         "<b>192.168.100.1</b>.",
         "perdi acesso rede ip mudei nao abre desfazer voltar"),
        ("luzes", "O que significam as luzes do dongle?",
         "<b>Verde aceso</b>: Wi-Fi do dongle ligado e com internet. <b>Verde "
         "piscando</b>: Wi-Fi ligado, mas sem internet. <b>Azul aceso</b>: conectado a "
         "outro Wi-Fi, com internet. <b>Azul piscando</b>: conectado, mas sem internet. "
         "<b>Vermelho aceso</b>: Wi-Fi desligado. <b>Vermelho piscando rápido</b>: algum "
         "erro. Ligado no computador, as luzes ficam apagadas. Com som tocando, a luz "
         "acesa pisca no ritmo. Detalhes em <a href='/leds'>Dispositivos › LEDs</a>.",
         "luz luzes led pisca piscando verde azul vermelho cor"),
        ("tor", "O que faz a navegação via Tor?",
         "Faz a internet de todos os aparelhos conectados ao dongle passar pela rede Tor, "
         "o que esconde o seu endereço dos sites. A navegação fica <b>bem mais lenta</b> "
         "e alguns sites bloqueiam ou pedem verificação. Liga e desliga em "
         "<a href='/tor'>Internet › Navegação via Tor</a>. Na primeira vez, ele baixa o "
         "programa.",
         "tor anonimo privacidade lento esconder ip"),
    ]),
    ("Acesso e segurança", [
        ("esqueci-senha", "Esqueci a senha do painel. Como recupero?",
         "A senha do painel é a mesma do SSH. Pra criar uma nova, use a <b>senha do "
         "root</b> que você cadastrou no primeiro uso: ligue o dongle no computador pelo "
         "cabo USB e abra o <b>console serial</b> que aparece no computador (velocidade "
         "115200, com PuTTY, screen ou similar). Entre como <b>root</b> e digite "
         "<b>passwd</b> seguido do seu nome de usuário pra escolher a senha nova. "
         "Se também esqueceu a senha do root, o último recurso é abrir o aparelho e "
         "reinstalar o sistema pelo modo EDL, o que <b>apaga tudo</b>.",
         "esqueci senha perdi recuperar redefinir trocar login nao lembro"),
        ("duas-senhas", "Qual a diferença entre a senha do root e a minha?",
         "A <b>sua senha</b> é a do dia a dia: entra neste painel e no SSH e permite "
         "tarefas de administração. A do <b>root</b> é da conta de manutenção do "
         "sistema e serve pra recuperar a sua, caso você a esqueça. Guarde as duas "
         "num lugar seguro. A sua senha e "
         "o seu nome de usuário podem ser trocados em "
         "<a href='/senha'>Geral › Conta e senha</a>.",
         "root senha diferenca usuario administrador sudo"),
        ("quem-conectado", "Como vejo quem está usando o meu dongle?",
         "Os aparelhos na rede do dongle aparecem em "
         "<a href='/rede'>Internet › LAN, DHCP e IP fixo</a>. Quem entrou no sistema "
         "por SSH aparece em <a href='/remoto'>Acesso remoto</a>, com um botão pra "
         "encerrar cada sessão. Se desconfiar de alguém, troque a senha do Wi-Fi e a "
         "sua senha.",
         "quem conectado aparelhos intruso estranho sessao ssh derrubar invasor"),
        ("acesso-longe", "Dá pra acessar o dongle de longe?",
         "Sim, com o <a href='/remoto'>Acesso remoto</a> (Tailscale, que tem conta "
         "gratuita). Não precisa abrir portas nem ter IP fixo e funciona até pelo 4G. "
         "Ele usa cerca de 30 MB de memória, então só fica ligado se você ligar.",
         "longe remoto fora de casa tailscale vpn acessar viagem"),
    ]),
    ("Aparelhos e som", [
        ("fone-bluetooth", "Como uso um fone ou caixa de som Bluetooth?",
         "1) Em <a href='/bluetooth'>Dispositivos › Bluetooth</a>, toque em "
         "<b>Procurar aparelhos</b> com o fone em modo de pareamento e depois em "
         "<b>Parear</b>. 2) Em <a href='/audio'>Áudio</a>, toque em <b>Ligar áudio "
         "Bluetooth</b>. Na primeira vez, ele baixa os programas de som, o que leva "
         "alguns minutos.",
         "fone caixa som bluetooth parear headset audio musica"),
        ("usb-aparelho", "Pluguei um pendrive ou placa de som USB e nada aconteceu.",
         "A porta USB só aceita aparelhos com o dongle <b>na tomada</b>, e normalmente "
         "precisa de um adaptador OTG. Ligado no computador, a porta está ocupada "
         "falando com o PC. Veja o que foi reconhecido em "
         "<a href='/usb'>Dispositivos › Aparelhos USB</a>.",
         "pendrive usb placa de som teclado mouse webcam nao reconhece otg"),
    ]),
    ("Sistema", [
        ("lento", "O dongle está lento ou travando. O que faço?",
         "Veja em <a href='/desempenho'>Geral › Desempenho</a> o que está usando memória "
         "e processador. Dá pra encerrar um programa por lá. Quando a memória acaba, o "
         "dongle fecha sozinho o programa que mais pesa, pra não travar. Se continuar, "
         "use <b>Reiniciar</b> em <a href='/geral'>Geral</a>. Recursos como Tor, acesso "
         "remoto e áudio Bluetooth usam memória: desligue os que não usa.",
         "lento travando travado memoria ram cheia devagar reiniciar"),
        ("atualizar", "Como atualizo o sistema?",
         "Em <a href='/atualizacoes'>Geral › Atualizações</a>, toque em <b>Procurar "
         "atualizações</b> e depois em <b>Instalar atualizações</b>. Precisa de "
         "internet, roda em segundo plano e a conexão pode piscar durante a "
         "instalação.",
         "atualizar atualizacao update versao nova sistema"),
        ("espaco", "Apareceu que o espaço está acabando.",
         "Em <a href='/espaco'>Geral › Espaço em disco</a>, veja o que está ocupando "
         "espaço e toque em <b>Liberar espaço</b>. Isso apaga só o que é seguro, como "
         "downloads de atualizações e registros antigos.",
         "espaco disco cheio armazenamento liberar"),
        ("backup-reset", "Como faço backup ou volto às configurações de fábrica?",
         "Em <a href='/sistema'>Geral › Nome, backup e reset</a>. O <b>backup</b> baixa "
         "um arquivo com as configurações do painel, incluindo as senhas do Wi-Fi: "
         "guarde com cuidado. O <b>reset</b> volta as configurações de rede ao padrão "
         "(Wi-Fi <b>{ssid}</b> / <b>{senha_wifi}</b>), mas não apaga seus arquivos nem "
         "troca a sua senha.",
         "backup copia reset fabrica restaurar padrao zerar configuracao"),
        ("hora-errada", "A hora do dongle está errada.",
         "Em <a href='/hora'>Geral › Data e hora</a>, confira o fuso horário. A hora "
         "automática precisa de internet. Sem ela, ajuste a data e a hora à mão por lá.",
         "hora data errada relogio fuso horario"),
        ("desligar", "Como desligo o dongle com segurança?",
         "Em <a href='/geral'>Geral</a>, toque em <b>Desligar</b> e espere uns 15 "
         "segundos antes de tirar da tomada. Pra ligar de novo, tire e recoloque.",
         "desligar desligamento tirar tomada seguro"),
        ("avancadas", "Onde ficam as opções avançadas?",
         "Ficam escondidas pra ninguém mudar sem querer. Em <a href='/geral'>Geral</a>, "
         "no cartão <b>Sobre</b>, toque 7 vezes em <b>OpenDongle</b>. Lá ficam os "
         "serviços do sistema, o kernel, os registros e o diagnóstico.",
         "avancado avancadas escondido desenvolvedor servicos kernel logs"),
    ]),
]
