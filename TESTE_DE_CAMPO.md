# Teste de campo do OpenDongle

Este documento serve pra quem vai **rodar** o teste (uma pessoa com o dongle na
mão) e pra quem vai **analisar** o resultado (outra pessoa ou um agente de IA).

## Objetivo

O back-end do painel já foi testado por HTTP e pela CLI. O que falta é o **uso
real**: tocar nos botões pelo celular, trocar o dongle entre PC e tomada, parear
um fone, deixar navegando por meia hora. Nessas situações aparecem falhas que um
teste automático não vê:

- tracebacks do painel ou de serviços que só acontecem numa sequência de toques;
- serviços que caem ou reiniciam em silêncio;
- falta de memória (OOM, earlyoom encerrando processos);
- travamentos (o dongle já travou antes com zram sem earlyoom);
- problemas na troca de modo USB (PC) ⇄ host (tomada);
- diferenças entre o que a tela promete e o que acontece.

O teste junta duas fontes: **o que a pessoa viu** (resultado e anotação de cada
passo do roteiro) e **o que o dongle registrou** (journal) no intervalo de cada
passo. O resultado é um `relatorio.md` com as falhas já cruzadas com os erros
do log.

Não é teste de interface visual. Ajustes de UX chegam separados, como protótipo
(HTML ou outro formato) pra adaptar no código.

## Peças

| Peça | O que é |
|---|---|
| `ferramentas/teste_campo.py` | Script que roda **no PC**. Contém o roteiro (fonte única) e todos os comandos. |
| `CHECKLIST_TESTE_CAMPO.md` | O mesmo roteiro em Markdown, pra ler no celular ou imprimir. Gerado com `teste_campo.py roteiro --markdown > CHECKLIST_TESTE_CAMPO.md`; regenere se mudar o roteiro. |
| `testes/campo-AAAAMMDD-HHMM/` | Uma pasta por sessão, fora do git (`.gitignore`): logs, respostas e relatório. |

### O que o script muda no dongle (e desfaz)

Só duas coisas, as duas removidas pelo `encerrar`:

1. `/etc/systemd/journald.conf.d/90-opendongle-teste.conf`: o journal grava em
   disco a cada 15 s. Sem isso, um travamento perde os últimos minutos de log.
   O journal do dongle já é persistente (`/var/log/journal`) e sobrevive a
   reboot e a tirar da tomada.
2. A **sentinela**: um timer do systemd a cada 30 s
   (`opendongle-sentinela.timer` + `/usr/local/sbin/opendongle-sentinela`) que
   escreve no journal uma linha com RAM disponível, swap, carga, temperatura,
   papel da porta USB e os 3 maiores processos. Não fica processo rodando entre
   uma leitura e outra. Buracos nessa sequência indicam travamento.

Nenhum processo de captura fica no ar: a RAM do dongle é justamente uma das
coisas sob teste.

## Como rodar (pessoa com o dongle)

Precisa, no PC: `python3` (3.10+), `ssh` e `sshpass`. A senha vai em
`OPENDONGLE_SENHA` ou é perguntada; ela nunca é gravada.

```bash
export OPENDONGLE_SENHA=1                        # ou deixe o script perguntar

# 1) dongle ligado no PC pelo USB
python3 ferramentas/teste_campo.py preparar

# 2) num segundo terminal, deixe aberto o tempo todo
python3 ferramentas/teste_campo.py acompanhar     # --tudo mostra também info e sentinela

# 3) no primeiro terminal, siga o roteiro
python3 ferramentas/teste_campo.py roteiro
#    em cada passo: o = ok · f = falhou (pede a descrição) · p = pular · v = voltar · s = sair
#    ao rodar de novo, continua do primeiro passo sem resposta
#    --passo ID começa por um passo específico (ex.: --passo bt-parear)

# 4) no fim, com o dongle alcançável (USB é o mais garantido)
python3 ferramentas/teste_campo.py coletar        # gera testes/campo-…/relatorio.md
python3 ferramentas/teste_campo.py encerrar       # tira a sentinela e o ajuste do journal
```

Dicas:

- **Descreva as falhas com detalhe.** "O botão Parear ficou girando e voltou
  sem o fone na lista" ajuda muito mais que "não funcionou". A anotação é a
  única fonte pra problemas que não deixam rastro no log.
- **Passos na tomada:** o PC perde o contato com o dongle, e é normal. Responda
  mesmo assim. O script avisa que ficou só o horário do PC, e o `coletar`
  encontra os logs daquele intervalo depois.
- **Trocou usuário ou senha num passo?** O script pede a credencial nova quando
  a antiga for recusada.
- **Testar o cadastro de primeiro uso:** `teste_campo.py senha-fabrica` volta a
  senha do usuário pra `1` (dongle no PC).
- **Não precisa fazer tudo de uma vez.** O roteiro continua de onde parou, e o
  `coletar` pode rodar mais de uma vez: ele refaz o relatório com tudo desde o
  `preparar`.
- **Nova sessão:** um novo `preparar` cria outra pasta. `acompanhar`, `roteiro`,
  `coletar` e `encerrar` usam sempre a sessão mais recente.

## Como analisar (outra pessoa ou agente)

Comece pelo `relatorio.md` da sessão e use os arquivos brutos pra aprofundar.

### Seções do relatório

- **Cabeçalho:** commit do repositório na hora do teste (e se havia mudanças
  locais), versão do dongle, desvio de relógio dongle × PC, placar dos passos,
  número de boots e menor RAM disponível vista pela sentinela.
- **Falhas apontadas no roteiro:** o que a pessoa descreveu e os erros e avisos
  do journal naquele intervalo. Se não houver erro no log, o problema
  provavelmente é de interface, de expectativa (o texto da tela promete outra
  coisa) ou fica fora do dongle (celular, rede, fone).
- **Erros no log em passos ok ou pulados:** falhas silenciosas. A pessoa não
  percebeu, mas algo quebrou por trás. Costumam ser as mais valiosas.
- **Erros fora de qualquer passo:** boot, tarefas em segundo plano (instalações
  de Tor, Tailscale, PipeWire, atualizações), timers.
- **Travamentos e reinícios:**
  - *Buraco na sentinela* (> 120 s sem leitura no mesmo boot): travamento ou
    congelamento. A última leitura antes do buraco mostra RAM, swap, carga e os
    maiores processos.
  - *Boot sem desligamento limpo*: pode ser só tirar da tomada, que é esperado
    em vários passos. Olhe o passo indicado antes de concluir que travou.
- **Observações** dos passos ok ou pulados, e **passos não feitos**.

### Arquivos brutos

| Arquivo | Conteúdo |
|---|---|
| `journal.jsonl` | Journal do dongle desde o `preparar` (todos os boots), 1 JSON por linha: `MESSAGE`, `PRIORITY`, `SYSLOG_IDENTIFIER`, `_SYSTEMD_UNIT`, `_BOOT_ID`, `__REALTIME_TIMESTAMP`. |
| `ao-vivo.log` | O que o `acompanhar` mostrou, com as quedas e voltas de conexão (útil pra saber quando o dongle sumiu). |
| `roteiro.json` | Resposta, anotação e horários (relógio do PC) de cada passo. |
| `sessao.json` | Início, desvio de relógio, commit, boot inicial. |
| `autosense.log` | Log do `usb-role-autosense.sh` (troca USB ⇄ host, 4G, grupos). |
| `boots.txt`, `servicos-falhos.txt` | `journalctl --list-boots` e `systemctl --failed` no fim. |
| `estado-inicial.txt`, `recursos-final.txt` | RAM e serviços antes e depois. |
| `estado-run.txt` | Estado do painel em `/run/opendongle/*.json`. |
| `config-mascarada.json` | `/etc/opendongle/config.json` com as senhas trocadas por `***`. |

Pra ler o journal de um passo à mão:

```bash
jq -r 'select(.SYSLOG_IDENTIFIER=="opendongle-teste") | .MESSAGE' journal.jsonl   # marcadores
jq -r 'select((.PRIORITY|tonumber) <= 3) | .MESSAGE' journal.jsonl               # erros pela prioridade
```

### Como os passos são ligados ao log

No início e no fim de cada passo, o roteiro manda `logger -t opendongle-teste
"PASSO <id> INICIO|FIM <resultado>"` pro dongle. Com o dongle fora de alcance
(passos na tomada), o relatório usa o horário do PC corrigido pelo desvio
medido no `preparar`. Um erro conta pro passo se cair entre o início e 30 s
depois do fim. Se as janelas se sobrepõem, vale o passo iniciado por último.

### Classificação e ruído

A classificação está em `teste_campo.py` (`RUIDO`, `ERRO`, `AVISO`):

- **erro:** prioridade do journal ≤ 3, ou texto como `Traceback`, `failed`,
  `Out of memory`, `Killed process`, `segfault`, `timed out`. A saída de erro
  dos serviços entra no journal com prioridade *info*, por isso o texto também
  conta.
- **aviso:** prioridade 4, ou `warning`, `retry`, `reset`.
- **ruído:** mensagens conhecidas da imagem que não são problema, como RTKit,
  UPower, `RequiresMountsFor` do `msm-firmware-loader`, sessões PAM já fechadas
  e os `sudo` do próprio script. O ruído fica fora do relatório.

Achou uma mensagem que é ruído de verdade? Acrescente em `RUIDO`, explique no
commit e rode `coletar` de novo: ele refaz o relatório a partir do
`journal.jsonl` baixado de novo.

### Fluxo sugerido depois da análise

1. Pra cada falha, separe: bug de back-end (com rastro no log), bug de
   interface, expectativa errada (texto da tela ou da Ajuda) e fatores externos.
2. Reproduza pelo HTTP ou pela CLI no dongle, quando possível, antes de mexer
   no código.
3. Corrija, envie ao dongle e peça pra pessoa repetir só os passos afetados:
   `teste_campo.py roteiro --passo <id>` numa sessão nova (`preparar`).
4. Se a correção mudar o que a tela promete, atualize o roteiro, regenere o
   `CHECKLIST_TESTE_CAMPO.md` e ajuste `core/opendongle/opendongle_ajuda.py`.

## Mudando o roteiro

O roteiro é a lista `ROTEIRO` em `teste_campo.py`: `(id, grupo, modo, título,
o que fazer, o que se espera)`.

- `modo`: `usb` (dongle no PC), `tomada` ou `qualquer`.
- **Não reaproveite ids.** Eles vão para os marcadores do log e para as
  sessões já gravadas.
- Escreva "o que se espera" de forma verificável por quem está com o celular
  na mão.
- Depois de mudar, regenere o `CHECKLIST_TESTE_CAMPO.md`.
