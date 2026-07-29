# 🔌 OpenDongle

> Transforme modems 4G descartados em pequenos servidores Linux — plugou, tomou um café, voltou, tá funcionando.

**OpenDongle** pega aqueles modems 4G USB baratos baseados no chip Qualcomm MSM8916 (os "dongles" que viram lixo eletrônico numa gaveta) e os transforma, de forma automatizada, em computadores Linux completos do tamanho de um pendrive — que gastam ~2W e ficam ligados o ano inteiro.

> ⚠️ **Status: em desenvolvimento ativo / fase de testes.** O fluxo de instalação do Debian está validado em hardware real. As etapas de otimização e do painel de configuração estão em teste. Veja a seção [Status](#status) antes de usar.

---

## 💡 Por que isso existe

Todo ano, o mundo descarta dezenas de milhões de toneladas de eletrônicos. Boa parte disso não é lixo de verdade — é tecnologia perfeitamente funcional que foi declarada "obsoleta" por quem a fabricou. Um modem 4G que a operadora aposentou ainda é um computador quad-core com Linux rodando dentro. A indústria fecha, esconde e descarta; este projeto abre, documenta e ressuscita.

A ideia central: **não faz sentido manter em cárcere uma tecnologia obsoleta.** Esses aparelhos podem virar bloqueadores de anúncios para a casa toda, VPNs pessoais, servidores de arquivos, cofres de senhas — infraestrutura útil e barata, feita de algo que iria para o aterro.

Este repositório é a **ponte** entre o excelente trabalho técnico da comunidade (que fez o Linux rodar nesses chips) e a pessoa comum que quer plugar e usar.

---

## 🙏 Créditos e base

O OpenDongle **não reinventa a roda** — ele automatiza e empacota, com muita documentação de campo, o trabalho de quem veio antes:

- **[OpenStick-Builder](https://github.com/LongQT-sea/OpenStick-Builder)** (por LongQT-sea) — a imagem Debian para MSM8916 que o OpenDongle instala. É o coração de tudo. Licença MIT.
- **[postmarketOS](https://postmarketos.org/)** — o trabalho de porting que tornou o Linux possível nesses chips.
- **[edl](https://github.com/bkerler/edl)** (por bkerler) — a ferramenta de comunicação com o modo Qualcomm EDL.

O OpenDongle é a camada de automação **por cima** dessas ferramentas, com o processo inteiro sistematizado e as armadilhas documentadas.

---

## 📦 O que tem aqui

O OpenDongle cobre a jornada inteira do dongle, do "lixo" ao "servidor pronto":

| Etapa | O que faz |
|-------|-----------|
| **Instalação** | Backup do firmware original → flash do Debian → verificação automática |
| **Otimização** | zram, logs em RAM, proteção do eMMC — deixa o Linux durar anos num chip barato |
| **Painel** | Rede Wi-Fi própria + página de configuração (`opendongle.local`) e comando `opendongle` |
| **Recuperação** | Restauração de backup e diagnóstico de placa para dongles "brickados" |

Tudo orquestrado por um único comando (`opendongle_completo.py`) que roda do PC e conduz o dongle do começo ao fim.

---

## 🚀 Uso rápido

> **Pré-requisito de acesso:** o processo conversa com o dongle várias vezes via SSH. Para não digitar a senha a cada etapa, o OpenDongle instala uma chave SSH automaticamente. Se preferir o método manual (recomendado publicar), pareie o PC com o dongle uma vez:
> ```
> ssh-copy-id -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null user@192.168.100.1
> ```
> Como atalho para processar muitos dongles em lote, instalar o `sshpass` (`sudo apt install -y sshpass`) deixa a instalação da chave 100% automática. É opcional.

**1. Prepare o ambiente** (baixa a imagem e as ferramentas):
```
sudo ./install.sh
python3 setup_estrutura.py
```

**2. Rode o processo completo** (com o dongle em modo EDL):
```
python3 opendongle_completo.py
```

O assistente pergunta se o Debian já está instalado, conduz a instalação, otimiza, instala o painel e configura o acesso USB. Ao final, o dongle sobe uma rede Wi-Fi chamada **OpenDongle** (senha `opendongle`) e responde em **opendongle.local**.

**3. Use.** Conecte no Wi-Fi do dongle, abra `opendongle.local`, e escolha o que ele vai ser.

---

## 🛠️ Os scripts

Para quem quer entender ou usar peça por peça:

- **`opendongle_completo.py`** — o orquestrador. Roda tudo de ponta a ponta.
- **`opendongle_autoinstall.py`** — instala o Debian (backup → flash → verificação), com detecção de placa e modo de teste.
- **`otimizar_dongle.py`** — aplica as otimizações de durabilidade e velocidade (reversível).
- **`instalar_opendongle.py`** — instala o painel de configuração (motor + CLI + web).
- **`opendongle/`** — o painel: motor único (`engine`), comando de terminal (`cli`), interface web (`web`) e o guardião de uplink (`uplink_guard`).
- **`restaurar_backup.py`** / **`restaurar_calibracao_ssh.py`** — recuperação.
- **`fable_detector.py`** — identifica o chip de qualquer dispositivo Qualcomm em EDL (ferramenta de exploração).

---

## 🎛️ O comando `opendongle`

O painel também é um comando de terminal no próprio dongle — a mesma lógica da interface web, no CLI:

```
sudo opendongle status                              # modo, internet, hotspot
sudo opendongle hotspot --ssid MinhaRede --senha minhasenha
sudo opendongle wifi --list                         # redes Wi-Fi visíveis
sudo opendongle wifi --ssid CasaX --senha segredo   # vira cliente de um Wi-Fi
sudo opendongle senha --nova umaSenhaForte          # troca a senha de admin
```

---

## ⚙️ Hardware alvo

- **Chip:** Qualcomm MSM8916 (Snapdragon 410), quad-core ARM64
- **RAM:** ~382 MB (por isso as otimizações importam tanto)
- **Placas testadas:** UZ801 e variantes. O instalador detecta ou testa a placa automaticamente.

---

## <a name="status"></a>✅ Status

| Componente | Estado |
|------------|--------|
| Instalação do Debian | ✅ Validado em hardware real |
| Backup / recuperação | ✅ Validado |
| Otimização (zram, eMMC) | 🧪 Em teste |
| Painel OpenDongle | 🧪 Em teste |
| Guardião de uplink | 🧪 Em teste |
| Suporte a placas além da UZ801 | ⏳ A confirmar |

---

## ⚠️ Avisos

- **Mexer no firmware tem risco.** O processo faz backup obrigatório antes de escrever, mas hardware é hardware. Comece por um dongle que você pode perder.
- **Sem chip SIM, sem 4G.** O dongle funciona como servidor/rede USB mesmo sem SIM, mas a função de modem depende de um chip ativo.
- **Este projeto instala software de terceiros** (a imagem OpenStick). O crédito é de quem o fez.

---

## 📄 Licença

MIT — veja [LICENSE](LICENSE). O OpenDongle usa a imagem OpenStick, também MIT (© 2024 GP Orcullo), cujo aviso de licença é mantido conforme exigido.

---

## 👤 Autor

Feito por **[@pianissimobr](https://github.com/pianissimobr)** — um entusiasta de reaproveitamento de hardware e inclusão digital, do Brasil. 🇧🇷

> Este projeto nasceu de uma pergunta simples: e se o "lixo eletrônico" fosse, na verdade, um tesouro esperando ser aberto?
