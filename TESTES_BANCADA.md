# Testes de bancada — rodada de set/2026

O que mudou nesta rodada e ainda precisa ser visto com as mãos (celular,
chip, adaptador serial). Os passos permanentes do dia a dia estão no
[CHECKLIST_TESTE_CAMPO.md](CHECKLIST_TESTE_CAMPO.md); este arquivo é só desta
rodada. Quando um teste falhar, anote o **horário**: o journal do dongle é
cronológico e o horário é o que liga o sintoma à causa.

Modo: **USB** = dongle ligado no PC · **tomada** = carregador, sem PC ·
**celular** = acesso pelo hotspot, sem cabo.

## O que ter à mão

- Celular com Wi-Fi (de preferência Android e iPhone, se tiver os dois)
- Um Wi-Fi de casa com a senha, e um segundo Wi-Fi qualquer (ou o roteador do celular)
- Chip SIM com dados (para o 4G)
- Opcional: adaptador serial USB-TTL 3,3 V (para a serial da placa)
- Opcional: um fone Bluetooth

---

## 1. Wi-Fi — lista vinda do boot

- [ ] **1.1 Varredura antes do hotspot** (tomada ou USB)
  - Fazer: desligue o dongle da energia, espere 10 s, ligue. Quando o hotspot aparecer, conecte o celular e abra Internet › Wi-Fi.
  - Esperado: a lista de redes já está lá, com "Último escaneamento agora mesmo" (ou "há 1 minuto"). O hotspot demorou só uns segundos a mais para aparecer.
  - Se falhar: `journalctl -b -u opendongle-wifi-boot` no dongle.

- [ ] **1.2 Idade da lista** (celular)
  - Fazer: feche a aba, espere uns 5 min e abra de novo.
  - Esperado: "Último escaneamento há 5 minutos" — e a tela abre sem derrubar o hotspot.

## 2. Wi-Fi — botão Buscar (o hotspot pausa)

- [ ] **2.1 Passo a passo antes de buscar** (celular)
  - Fazer: toque em Buscar.
  - Esperado: aparece o passo a passo (vai perder a conexão · reconecte ao "OpenDongle" · a lista chega sozinha) com "Entendi, buscar" e "Cancelar". Cancelar não faz nada.

- [ ] **2.2 Busca de verdade** (celular)
  - Fazer: toque em "Entendi, buscar". Quando o celular cair, reconecte ao Wi-Fi "OpenDongle" (se ele pular sozinho para o Wi-Fi de casa, volte à mão) e volte à aba do navegador.
  - Esperado: a lista nova aparece sozinha, com "agora mesmo". O hotspot ficou fora uns 2 s.
  - Se falhar: `journalctl -u opendongle-wifi-busca` no dongle. Se aparecer "hotspot demorando a voltar", a fila do systemd está logo abaixo — é o registro do atraso de 30 s visto uma vez.

- [ ] **2.3 Busca pelo cabo** (USB)
  - Fazer: pelo PC, em Internet › Wi-Fi, toque em Buscar e confirme.
  - Esperado: a lista atualiza em poucos segundos e o painel não perde a conexão (o cabo não depende do hotspot).

## 3. Wi-Fi — conectar e achar o dongle

- [ ] **3.1 Rede já usada antes (senha salva)** (celular)
  - Fazer: escolha o Wi-Fi de casa (marcado "salva"), deixe a senha em branco, toque em Continuar → Conectar. Conecte o celular ao Wi-Fi de casa e toque em "Encontrar meu dongle".
  - Esperado: acha em ~1 s e mostra "Seu dongle está em http://192.168.x.y". "Abrir o painel" leva ao login.
  - Anote: o IP mostrado. Na próxima vez nessa rede ele deve ser o mesmo (lease fixo).

- [ ] **3.2 Rede nova** (celular)
  - Fazer: volte o dongle ao hotspot (Internet › Hotspot, ou desligue e ligue da tomada). Conecte a uma rede em que ele nunca esteve, digitando a senha. Siga o passo a passo.
  - Esperado: "Encontrar meu dongle" acha em alguns segundos.
  - Teste nos dois celulares se puder: no **iPhone** costuma achar na hora (mDNS); no **Android** pode levar uns 5–15 s (varredura da faixa).
  - Se o navegador pedir permissão para "acessar dispositivos da rede local", **anote qual navegador e versão** — é o único ponto que não consegui testar.

- [ ] **3.3 Senha errada** (celular)
  - Fazer: conecte a uma rede com a senha errada de propósito. Siga o passo a passo; no Wi-Fi de casa, "Encontrar meu dongle" não vai achar.
  - Esperado: a tela explica (senha errada → o dongle volta ao hotspot em ~1 min). Depois de ~1 min, o hotspot "OpenDongle" volta; conecte e abra Internet › Wi-Fi.
  - Esperado também: um aviso "A última tentativa de conectar a X não deu certo: não associou…".

- [ ] **3.4 Digitar o nome da rede** (celular)
  - Fazer: "Digitar o nome da rede", escreva o nome exato de uma rede (com maiúsculas) e a senha.
  - Esperado: conecta como nas outras. Com nome errado, cai no fluxo da senha errada (3.3).

- [ ] **3.5 Rede aberta** (celular, se houver uma por perto)
  - Esperado: aparece com a etiqueta "Aberta" e não pede senha.

## 4. Relógio

- [ ] **4.1 Liga atrasado, corrige pelo celular** (tomada + celular, **sem internet no dongle**)
  - Fazer: deixe o dongle desligado uns 15 min. Ligue na tomada (sem chip e sem Wi-Fi de casa configurado). Conecte o celular ao hotspot e abra o painel.
  - Esperado: em Sistema › Hora, a hora bate com a do celular (antes de abrir o painel estaria ~15 min atrasada).
  - Conferir pelo terminal: `timedatectl` mostra "System clock synchronized: no" (normal sem internet) e a hora certa.

## 5. Console serial

- [ ] **5.1 Serial pela USB pede login** (USB)
  - Fazer: no PC, `sudo screen /dev/ttyACM0 115200`, Enter.
  - Esperado: `opendongle login:` — entra com o seu usuário e senha.
  - Se aparecer "Login incorrect" sozinho logo após plugar: é o ModemManager do PC mandando `AT` (ver TROUBLESHOOTING_pt.md, seção de rede USB).

- [ ] **5.2 Serial da placa sem loop** (com adaptador; qualquer)
  - Fazer: ligue o adaptador nos pontos TX/RX/GND (3,3 V!), 115200 baud.
  - Esperado: mensagens do boot e um `login:` que **fica parado** esperando (antes ele reiniciava a cada 60 s).
  - Sem adaptador: `systemctl show serial-getty@ttyMSM0 -p NRestarts` depois de 10 min ligado deve dar `0`.

## 6. Diagnóstico e telas avançadas

- [ ] **6.1 Diagnóstico nas duas línguas** (qualquer)
  - Fazer: Opções avançadas › Diagnóstico › Rodar. Troque o idioma do painel para English.
  - Esperado: os testes e os detalhes mudam de língua junto com o resto da tela. O modem aparece ✅ ("modem responde").

- [ ] **6.2 Serviços** (qualquer)
  - Fazer: abra Serviços do sistema duas vezes seguidas; desligue e religue o `cron`.
  - Esperado: a primeira abertura leva ~3 s, a segunda é quase instantânea; o `cron` muda de estado e a lista atualiza sozinha. Tentar desligar um essencial mostra o motivo da recusa.

- [ ] **6.3 Painel abrindo mais rápido** (qualquer)
  - Esperado: páginas e ações respondem visivelmente mais rápido que antes (o `/api/tudo` caiu de ~4 s para ~1,7 s).

## 7. Áudio Bluetooth (com fone)

- [ ] **7.1 Fone aparece com o áudio BT ligado** (qualquer)
  - Fazer: Dispositivos › Áudio, ligue o áudio Bluetooth; pareie e conecte um fone.
  - Esperado: o fone aparece em "Fones e caixas Bluetooth", e as placas de som continuam listadas (antes, com o BT ligado, a tela de áudio ficava vazia).

- [ ] **7.2 Música ↔ chamada** (qualquer)
  - Fazer: troque o modo do fone entre Música e Chamada.
  - Esperado: troca sem erro (antes dava "aparelho não encontrado"). Em Chamada aparece o microfone do fone em Entradas.

## 8. 4G com chip

- [ ] **8.1 Chip reconhecido** (qualquer)
  - Fazer: com o dongle **desligado**, insira o chip; ligue.
  - Esperado: Internet › Modem 4G mostra "Chip SIM: Presente" e a operadora.

- [ ] **8.2 Rádio ligado e registro** (qualquer)
  - Fazer: toque em "Reconectar 4G".
  - Esperado: sinal em dBm, operadora e "Registrado".
  - **Anote o IMEI mostrado.** Ele está zerado (`000000000000000`); se a operadora recusar o registro por isso, o próximo passo é regravar o IMEI da etiqueta deste aparelho.
  - Se falhar: `sudo opendongle modem` no terminal e o horário.

- [ ] **8.3 Internet pelo 4G sozinho, na tomada** (tomada)
  - Fazer: com o chip, ligue o dongle na tomada (sem PC) e espere ~1 min. Conecte o celular ao hotspot.
  - Esperado: internet no celular pelo 4G, sem apertar nada (o boot agora liga o rádio pelo QMI).
  - Se falhar: `journalctl -b -u usb-role-autosense` — procure "4G: radio em modo" e "4G: SIM MCCMNC".
  - Pelo PC (USB) o 4G continua não subindo sozinho: é o desenho atual (o 4G automático só roda na tomada).

## 9. Cadastro real (primeiro uso)

- [ ] **9.1 Fluxo completo** (celular)
  - ⚠️ Apaga as credenciais atuais — faça quando puder recriar o acesso ali mesmo.
  - Esperado: o cadastro aparece sozinho, aceita nome, usuário, senha e foto, e depois disso o painel pede login com os dados novos (inclusive no SSH).

## 10. Localizador de PC

- [ ] **10.1 PC com duas redes** (dongle no Wi-Fi de casa)
  - Fazer: num notebook ligado no **cabo** (rota padrão) e no Wi-Fi ao mesmo tempo, com o dongle no Wi-Fi: `python3 ferramentas/opendongle_localizar.py`.
  - Esperado: acha o dongle pelo IP do Wi-Fi, mostrando o id. É o cenário que a versão antiga não pegava.
  - Windows e macOS também valem: o script lê `ipconfig`/`ifconfig`.

## 11. Instalação limpa (outro dongle)

- [ ] **11.0 Backup de rádio ANTES de tudo** — em todos os dongles que já rodam Debian
  - Fazer, para cada um, com o IMEI da **etiqueta**:
    `python3 ferramentas/backup_radio.py --imei <IMEI da etiqueta> --usuario <seu usuário>`
  - Esperado: "Backup completo e conferido", numa pasta `backups-radio/<IMEI>/<data>/`.
  - Se aparecer **"só zeros"** em `modemst1/2`, `fsg`, `persist` ou `modem`: aquele aparelho já perdeu a identidade — anote.
  - Depois: copie `backups-radio/` para fora do PC (HD externo ou nuvem). Ver `backups-radio/LEIAME.md`.
  - Nos dongles novos, "super limpos": o mesmo script assim que tiverem Debian, ou o dump por EDL antes do primeiro flash.

- [ ] **11.1 Instalador de ponta a ponta**
  - Fazer: rode o `core/instalar_opendongle.py` num dongle recém-flasheado.
  - Esperado: termina sem erro, e depois do reboot:
    - `systemctl is-enabled opendongle-wifi-boot` → `enabled`;
    - `ls /etc/systemd/system/serial-getty@ttyMSM0.service.d/` mostra só `10-opendongle-login.conf` (o `override.conf` da imagem foi removido);
    - a lista de Wi-Fi já vem do boot (teste 1.1).

---

## Pendências conhecidas (não são testes)

1. ~~4G não liga sozinho no boot~~ — corrigido: o boot liga o rádio pelo QMI e usa a porta AT que existir.
2. **IMEI zerado** no dongle de teste: nenhum backup tinha o IMEI. Se a operadora recusar, regravar o IMEI da etiqueta.
3. ~~`/api/tudo` duas vezes e erro de hidratação #418~~ — corrigido (o provedor de dados saiu de dentro da troca de idioma; a saúde não mostra mais número simulado antes da leitura real).
4. **Rajadas de `qmicli` podem derrubar uma porta AT** do modem (visto com 8 leituras em paralelo). O diagnóstico e o boot já usam a porta que sobrar, e com o item 3 o painel não dispara mais leituras em dobro.
5. ~~Sobras de teste no dongle~~ — limpas; o backup de rádio B foi para `backups-radio/_conjunto-B-origem-desconhecida/`.
6. **Regra de udev do ModemManager** neste PC: documentada, não aplicada.
7. **Mensagens do motor só em português** fora do diagnóstico (erros e avisos das ações).
