# 🔧 Guia de Solução de Problemas — OpenDongle

Este documento é o mapa das armadilhas que encontramos (apanhando) ao
domar esses dongles. Se você está travado num erro, provavelmente ele
está aqui — com a explicação do **porquê** acontece e o **como** resolver.

> A filosofia aqui é a mesma do projeto: quase todo "problema" desses
> dongles assusta mais do que machuca. Na maioria das vezes o aparelho
> está bem — quem se perde é o processo. Leia com calma.

---

## Índice

- [Modo EDL e comunicação](#edl)
- [O loader (firehose)](#loader)
- [Boot, fastboot e ADB](#boot)
- [O "travamento" que não é travamento](#travamento)
- [Rede USB e acesso ao dongle](#rede)
- [SSH pedindo senha o tempo todo](#ssh)
- [Detecção de placa](#placa)
- [Calibração e 4G](#calibracao)

---

## <a name="edl"></a>🔌 Modo EDL e comunicação

### O dongle não aparece em EDL (`lsusb` não mostra `05c6:9008`)

O EDL (Emergency Download Mode) é o modo de resgate gravado na ROM do
chip — ele está **abaixo** de tudo que você possa ter quebrado, e por
isso quase sempre funciona. Para entrar: desligue o dongle e religue
**segurando o botão** (o furinho na carcaça, ou o test point interno).

Se mesmo assim não aparecer:
- Confira o cabo — precisa ser um cabo de **dados**, não só de carga.
- Troque de porta USB (de preferência traseira, direto na placa-mãe).
- Pare o ModemManager, que "sequestra" a porta: `sudo systemctl stop ModemManager`

### "sahara - Couldn't find a loader for given hwid and pkhash"

Ver a seção [O loader](#loader) — este é o erro mais comum e tem
solução direta.

### Comandos edl travando ("Waiting for the device")

Geralmente é uma destas três coisas:
1. **ModemManager** segurando a porta → `sudo systemctl stop ModemManager`
2. **Estado Sahara consumido** — se um comando edl anterior já tocou o
   aparelho, o handshake foi usado. **Solução: desplugue e replugue em
   EDL** e tente de novo. Isso resolve a maioria dos travamentos.
3. Cabo/porta ruim.

---

## <a name="loader"></a>📦 O loader (firehose)

### "Couldn't find a loader for given hwid and pkhash"

Este é o erro que trava quase todo mundo no começo, e a explicação é
elegante: o modo EDL funciona em duas fases. Primeiro o protocolo
**Sahara** identifica o chip (você vê o HWID, o PK_HASH, o serial). Em
seguida, ele precisa enviar um **programador firehose** — um pequeno
binário que roda dentro do chip e faz as leituras/escritas de verdade.

O `edl` tenta escolher esse programador sozinho, casando pelo par
HWID + PK_HASH. Nesses dongles, o par é a **chave de teste pública da
Qualcomm** (PK_HASH começando com `cc3153a8...`, OEM_ID `0x0000`) —
uma combinação que não está no banco automático do edl. Por isso ele
identifica o chip mas não acha o loader.

**Solução:** passar o loader genérico do MSM8916 explicitamente. O
OpenDongle já baixa e valida esse arquivo (`setup_estrutura.py`) e o
passa em todo comando (`--loader=...`). Se você faz na mão:
```
edl --loader=prog_emmc_firehose_8916.mbn <comando>
```

---

## <a name="boot"></a>🥾 Boot, fastboot e ADB

### O dongle sobe como Android (aparece em `adb`) em vez de fastboot

Sintoma: depois de gravar o aboot, você espera o fastboot, mas o
dongle sobe o Android de fábrica e aparece em `adb devices`.

**Por quê:** o comando que apaga a partição `boot` falhou
silenciosamente (nesses dongles, o `edl e boot` às vezes reporta
"No storage drive number" e mesmo assim imprime "Erased"). Com o boot
stock intacto, o bootloader custom encontra um Android válido e o
inicia.

**Solução:** invalidar o boot de forma determinística — escrever zeros
no início da partição, destruindo o "magic" do boot.img. O OpenDongle
faz isso automaticamente. Na mão, via EDL:
```
edl --loader=... w boot zeros_1mb.bin
```

### `adb reboot bootloader` não funciona neste stock

Alguns firmwares de fábrica desses dongles não honram o
`adb reboot bootloader` (o kernel não grava a flag que o bootloader
lê). Nesse caso, o caminho é o EDL: replugue segurando o botão e
invalide o boot por lá. O OpenDongle detecta o estado e trata isso
sozinho no seu autômato de recuperação.

---

## <a name="travamento"></a>⏳ O "travamento" que não é travamento

Esta é a lição mais importante do projeto inteiro, então preste
atenção: **na maioria das vezes que parece que travou, não travou.**

### O flash "trava" no fim do rootfs

Sintoma: o `fastboot flash rootfs` fica parado sem output, às vezes
por vários minutos, e parece morto.

**A verdade:** o `fastboot` fica **mudo** durante escritas longas — ele
só imprime o "Finished" no final. O rootfs é a maior partição (vários
GB), então esse silêncio pode durar **6 minutos ou mais** e ser
totalmente normal. Interromper aqui é o erro clássico (nós matamos uma
escrita legítima com um watchdog curto demais, mais de uma vez).

**Solução:** paciência, e um watchdog tolerante (o OpenDongle usa 15
minutos). Se você fatiar a transferência em pedaços menores
(`fastboot -S 128M`), evita o problema — o dongle troca status com mais
frequência e não fica em silêncio longo.

### O dongle "brickou" durante o flash

Antes de entrar em pânico: **teste se ele ainda entra em EDL**
(replug com botão, `lsusb`). Se entra — e quase sempre entra — ele
**não brickou**. O EDL é o resgate na ROM. Você pode reinstalar do
zero por ali.

Aconteceu conosco de um dongle parecer completamente morto (não
enumerava mais no USB) depois de um flash interrompido — e ele estava
perfeitamente vivo em EDL, totalmente recuperável.

---

## <a name="rede"></a>🌐 Rede USB e acesso ao dongle

### O dongle apareceu como rede, mas eu perdi a internet do PC

Sintoma clássico: você pluga o dongle, ele vira uma "rede cabeada", e
seu PC perde o acesso à internet.

**Por quê:** seu PC, ao ver a rede nova, tenta usá-la como caminho para
a internet. Mas o dongle (sem chip SIM) não leva a lugar nenhum, e seu
PC abandona o Wi-Fi que tinha internet.

**Solução (no PC):** dizer ao sistema para nunca usar o dongle como
saída de internet:
```
nmcli connection modify "Conexão cabeada X" ipv4.never-default yes ipv6.never-default yes
nmcli connection down "Conexão cabeada X" && nmcli connection up "Conexão cabeada X"
```
(troque `"Conexão cabeada X"` pelo nome real, visto com `nmcli connection show`.)

**Solução permanente (no dongle):** o OpenDongle instala um guardião
(`uplink_guard`) que só anuncia o dongle como provedor de internet
quando ele **tem** internet de verdade. Assim, qualquer PC que plugar
já se comporta certo, sem configuração.

### O dongle demora a aparecer como rede após instalar

Alguns dongles não religam sozinhos após o reset — precisam de um
replug (sem botão). E o primeiro boot do Debian é o mais lento (ele
redimensiona o sistema de arquivos e gera chaves): **2 a 4 minutos de
espera são normais** antes de ele responder em `192.168.100.1`.

---

## <a name="ssh"></a>🔑 SSH pedindo senha o tempo todo

### Cada etapa pede a senha de novo

Sintoma: o processo pede `user@192.168.100.1's password:` repetidas
vezes, uma por etapa. Além de irritante, é **arriscado** — se você
errar a senha no meio, uma etapa pode falhar silenciosamente.

**Por quê:** sem uma chave SSH instalada, cada conexão nova pede senha.

**Solução:** instalar sua chave pública no dongle **uma vez**:
```
ssh-copy-id -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null user@192.168.100.1
```
Digite a senha (`1`) uma última vez. Depois disso, nenhuma conexão pede
senha. O OpenDongle tenta fazer isso automaticamente; instalar o
`sshpass` (`sudo apt install -y sshpass`) torna esse passo 100%
automático.

### "WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!"

Assustador, mas **inofensivo** no nosso caso. Acontece porque você
reinstalou um dongle e ele gerou uma chave SSH nova — mas seu PC ainda
guardou a chave antiga daquele mesmo IP. Não é ataque.

**Solução:**
```
ssh-keygen -f ~/.ssh/known_hosts -R 192.168.100.1
```
E conecte de novo. (Como todos os dongles usam o mesmo IP, isso se
repete a cada reinstalação — por isso os scripts do OpenDongle ignoram
essa verificação para o IP de bancada.)

---

## <a name="placa"></a>🔍 Detecção de placa

### O scan não achou nenhuma assinatura de placa

Normal, não é falha. O firmware de fábrica de alguns dongles não
carrega as strings de modelo em texto simples, então o scan retorna
zero. Nesse caso o OpenDongle cai no **modo teste**: ele instala e
verifica placa por placa (trocando só o devicetree) até o sistema
subir com rede — a que subir é a placa certa.

### Como sei que a placa está certa?

O teste definitivo é o **Wi-Fi**: se a rede Wi-Fi do dongle aparece e
funciona, o devicetree está correto (o Wi-Fi é o subsistema mais
sensível a devicetree errado). A rede USB subir já é um bom sinal; o
Wi-Fi subir é a confirmação final.

---

## <a name="calibracao"></a>📡 Calibração e 4G

### Instalei o Debian mas o 4G não funciona

Duas causas possíveis:

1. **Sem chip SIM.** Óbvio, mas vale checar — sem SIM não há 4G. O
   dongle ainda funciona como servidor/rede USB normalmente.

2. **Calibração não restaurada.** A tabela de partições nova reorganiza
   o disco, e as partições de rádio (modem, calibração, IMEI) precisam
   ser restauradas do backup. Se a instalação foi interrompida antes
   dessa etapa, o 4G não sobe. Restaure com:
   ```
   python3 restaurar_calibracao_ssh.py
   ```

### Perdi o backup de um dongle — dá para recuperar?

Depende do que você quer:
- **Voltar ao Android de fábrica:** não, sem o backup original isso
  não é possível (a chance de capturar o stock passou no primeiro flash).
- **Ter o dongle funcionando com Debian:** sim, tranquilamente — você
  não precisa de backup para isso. Só a calibração/IMEI original pode
  não voltar, o que só importa se você for usar o 4G.

---

## Não achou seu problema aqui?

Se o dongle entra em EDL, ele é recuperável — comece por aí. Abra uma
issue descrevendo o erro exato, o que aparece no `lsusb`, e em que
etapa travou. Quanto mais específico, mais fácil ajudar.
