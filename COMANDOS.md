# 🎛️ O comando `opendongle`

[English](COMMANDS.md) · **Português**

O painel também é um comando de terminal no próprio dongle — a mesma lógica da
interface web, no CLI. Veja o [README](README_pt.md) para o resto do projeto.

```
sudo opendongle status                              # modo, internet, hotspot
sudo opendongle hotspot --ssid MinhaRede --senha minhasenha
sudo opendongle wifi --list                         # redes Wi-Fi visíveis
sudo opendongle wifi --ssid CasaX --senha segredo   # vira cliente de um Wi-Fi
sudo opendongle modem                               # chip, operadora, sinal e diagnóstico do 4G
sudo opendongle modem --apn claro.com.br            # APN da operadora do chip atual
sudo opendongle modem --reconectar                  # liga o rádio e refaz a conexão 4G
sudo opendongle senha --nova umaSenhaForte          # troca a senha de admin
sudo opendongle usuario --novo lucas                # troca o nome do usuário (mesmo UID, sudo e senha)
sudo opendongle diagnostico                         # testa áudio, Bluetooth, vídeo USB e modem 4G
sudo opendongle recursos                            # RAM usada por serviço
sudo opendongle config show                         # config central (config aplicar pra reaplicar)
sudo opendongle config set lan.dhcp.inicio=20       # altera e aplica (como o uci set)
sudo opendongle dhcp clientes                       # aparelhos conectados (fixar/soltar IP fixo)
sudo opendongle redir add --nome web --porta-externa 8080 --ip 192.168.100.20 --porta-interna 80
sudo opendongle logs dnsmasq                        # log do sistema ou de um serviço
sudo opendongle hardware                            # placa, eMMC e desgaste, rádios, modem
sudo opendongle hora status|auto on|ajustar DATA HORA
sudo opendongle espaco analisar|liberar             # o que ocupa o disco e limpeza
sudo opendongle atualizacoes verificar|instalar     # roda em segundo plano
sudo opendongle reiniciar|desligar
sudo opendongle bluetooth status|buscar|parear MAC  # parear com PIN/código: responder sim|PIN
sudo opendongle usb [host|device]                   # aparelhos USB e papel da porta
sudo opendongle audio                               # placas de som (volume, mudo, padrao, testar)
sudo opendongle audio bluetooth on|off              # PipeWire sob demanda pra fone/caixa Bluetooth
sudo opendongle servicos [ligar|desligar NOME]      # serviços do boot (essenciais protegidos)
sudo opendongle tor on|off|status                   # navegação da LAN pela rede Tor (instala na 1ª vez)
sudo opendongle remoto on [--lan] [--saida]         # acesso remoto via Tailscale (login|logout|status|off)
sudo opendongle backup > backup.json                # exporta a config
sudo opendongle restaurar backup.json               # restaura e aplica um backup
sudo opendongle reset                               # volta à configuração de fábrica
sudo opendongle rede confirmar                      # confirma mudança de rede (senão ela volta sozinha em 3 min)
```
