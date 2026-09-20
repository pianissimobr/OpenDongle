# 🎛️ The `opendongle` command

**English** · [Português](COMANDOS.md)

The panel is also a terminal command on the dongle itself — the same logic as
the web interface, in the CLI. See the [README](README.md) for the rest of the
project. (Flags and messages are in Portuguese, matching the device.)

```
sudo opendongle status                              # mode, internet, hotspot
sudo opendongle hotspot --ssid MyNetwork --senha mypassword
sudo opendongle wifi --list                         # visible Wi-Fi networks
sudo opendongle wifi --ssid HomeX --senha secret    # join an existing Wi-Fi as a client
sudo opendongle senha --nova aStrongPassword        # change the admin password
sudo opendongle usuario --novo lucas                # rename the user (same UID, sudo and password)
sudo opendongle diagnostico                         # test audio, Bluetooth, USB video and the 4G modem
sudo opendongle recursos                            # RAM used per service
sudo opendongle config show                         # central config (config aplicar to re-apply)
sudo opendongle config set lan.dhcp.inicio=20       # change and apply (like uci set)
sudo opendongle dhcp clientes                       # connected devices (pin/unpin a static IP)
sudo opendongle redir add --nome web --porta-externa 8080 --ip 192.168.100.20 --porta-interna 80
sudo opendongle logs dnsmasq                        # system log, or a single service
sudo opendongle hardware                            # board, eMMC and wear, radios, modem
sudo opendongle hora status|auto on|ajustar DATE TIME
sudo opendongle espaco analisar|liberar             # what fills the disk, and cleanup
sudo opendongle atualizacoes verificar|instalar     # runs in the background
sudo opendongle reiniciar|desligar                  # reboot | power off
sudo opendongle bluetooth status|buscar|parear MAC  # pair with PIN/code: responder sim|PIN
sudo opendongle usb [host|device]                   # USB devices and the port role
sudo opendongle audio                               # sound cards (volume, mute, default, test)
sudo opendongle audio bluetooth on|off              # PipeWire on demand for a Bluetooth headset/speaker
sudo opendongle servicos [ligar|desligar NAME]      # boot services (essential ones are protected)
sudo opendongle tor on|off|status                   # route the LAN through Tor (installs on first use)
sudo opendongle remoto on [--lan] [--saida]         # remote access via Tailscale (login|logout|status|off)
sudo opendongle backup > backup.json                # export the config
sudo opendongle restaurar backup.json               # restore and apply a backup
sudo opendongle reset                               # back to factory configuration
sudo opendongle rede confirmar                      # confirm a network change (else it reverts on its own in 3 min)
```
