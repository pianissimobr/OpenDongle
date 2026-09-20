export type IconName =
  | "house"
  | "globe"
  | "user"
  | "cable"
  | "settings"
  | "help"
  | "wrench"

export type Categoria = {
  id: string
  icon: IconName
  nome: string
  nomeEn: string
  rota: string
}

export const CATEGORIAS: Categoria[] = [
  { id: "inicio", icon: "house", nome: "Início", nomeEn: "Home", rota: "/" },
  { id: "internet", icon: "globe", nome: "Internet", nomeEn: "Internet", rota: "/internet" },
  { id: "perfil", icon: "user", nome: "Perfil", nomeEn: "Profile", rota: "/perfil" },
  { id: "dispositivos", icon: "cable", nome: "Dispositivos", nomeEn: "Devices", rota: "/dispositivos" },
  { id: "sistema", icon: "settings", nome: "Sistema", nomeEn: "System", rota: "/sistema" },
]

export const CAT_AJUDA: Categoria = { id: "ajuda", icon: "help", nome: "Ajuda", nomeEn: "Help", rota: "/ajuda" }
export const CAT_AVANCADAS: Categoria = { id: "avancadas", icon: "wrench", nome: "Avançado", nomeEn: "Advanced", rota: "/avancadas" }

export const CATEGORIA_DA_ROTA: Record<string, string> = {
  "/": "inicio",
  "/internet": "internet",
  "/hotspot": "internet",
  "/wifi": "internet",
  "/wifi-conectado": "internet",
  "/modem": "internet",
  "/rede": "internet",
  "/firewall": "internet",
  "/remoto": "internet",
  "/tor": "internet",
  "/confirmar": "internet",
  "/perfil": "perfil",
  "/senha": "perfil",
  "/dispositivos": "dispositivos",
  "/bluetooth": "dispositivos",
  "/usb": "dispositivos",
  "/audio": "dispositivos",
  "/leds": "dispositivos",
  "/sistema": "sistema",
  "/hora": "sistema",
  "/atualizacoes": "sistema",
  "/status": "sistema",
  "/desempenho": "sistema",
  "/espaco": "sistema",
  "/hardware": "sistema",
  "/nome-backup": "sistema",
  "/ajuda": "ajuda",
  "/avancadas": "avancadas",
  "/logs": "avancadas",
  "/diagnostico": "avancadas",
  "/kernel": "avancadas",
  "/recursos": "avancadas",
  "/config-arquivo": "avancadas",
  "/servicos": "avancadas",
}

export type BuscaItem = { titulo: string; tituloEn: string; rota: string; palavras: string }

export const BUSCA: BuscaItem[] = [
  { titulo: "Início", tituloEn: "Home", rota: "/", palavras: "inicio home principal main" },
  { titulo: "Perfil", tituloEn: "Profile", rota: "/perfil", palavras: "perfil conta usuario senha avatar foto identidade profile account user password photo" },
  { titulo: "Status e saúde", tituloEn: "Status and health", rota: "/status", palavras: "status saude cpu ram memoria disco temperatura health memory disk temperature" },
  { titulo: "Wi-Fi e hotspot", tituloEn: "Wi-Fi and hotspot", rota: "/hotspot", palavras: "wifi hotspot rede senha ssid network password" },
  { titulo: "Conectar a uma rede Wi-Fi", tituloEn: "Connect to a Wi-Fi network", rota: "/wifi", palavras: "conectar wifi cliente rede casa connect client home network" },
  { titulo: "Modem 4G", tituloEn: "4G modem", rota: "/modem", palavras: "4g chip sim operadora apn sinal modem carrier signal" },
  { titulo: "LAN, DHCP e IP fixo", tituloEn: "LAN, DHCP and static IP", rota: "/rede", palavras: "lan dhcp ip fixo clientes aparelhos static devices" },
  { titulo: "Firewall e portas", tituloEn: "Firewall and ports", rota: "/firewall", palavras: "firewall porta redirecionar ssh bloquear port forward block" },
  { titulo: "Acesso remoto", tituloEn: "Remote access", rota: "/remoto", palavras: "remoto tailscale vpn longe acesso remote away access" },
  { titulo: "Navegação via Tor", tituloEn: "Browsing via Tor", rota: "/tor", palavras: "tor anonimo privacidade onion anonymous privacy" },
  { titulo: "Bluetooth", tituloEn: "Bluetooth", rota: "/bluetooth", palavras: "bluetooth parear fone caixa teclado controle pair headset speaker keyboard" },
  { titulo: "Aparelhos USB", tituloEn: "USB devices", rota: "/usb", palavras: "usb pendrive teclado placa som host otg flash drive keyboard sound card" },
  { titulo: "Áudio", tituloEn: "Audio", rota: "/audio", palavras: "audio som fone microfone volume mudo musica chamada sound headset microphone mute music call" },
  { titulo: "LEDs", tituloEn: "LEDs", rota: "/leds", palavras: "led luz luzes piscar light lights blink" },
  { titulo: "Conta e senha", tituloEn: "Account and password", rota: "/senha", palavras: "senha admin trocar password login entrar change sign in account" },
  { titulo: "Data e hora", tituloEn: "Date and time", rota: "/hora", palavras: "data hora relogio fuso horario date time clock timezone" },
  { titulo: "Atualizações", tituloEn: "Updates", rota: "/atualizacoes", palavras: "atualizar atualizacao update sistema upgrade system" },
  { titulo: "Espaço em disco", tituloEn: "Disk space", rota: "/espaco", palavras: "espaco disco cheio armazenamento liberar space disk storage free clean" },
  { titulo: "Desempenho", tituloEn: "Performance", rota: "/desempenho", palavras: "desempenho cpu ram processos lento performance processes slow" },
  { titulo: "Hardware", tituloEn: "Hardware", rota: "/hardware", palavras: "hardware placa chip emmc imei mac board" },
  { titulo: "Nome, backup e reset", tituloEn: "Name, backup and reset", rota: "/nome-backup", palavras: "nome backup reset fabrica name factory" },
  { titulo: "Logs do sistema", tituloEn: "System logs", rota: "/logs", palavras: "logs journalctl servico service" },
  { titulo: "Diagnóstico de hardware", tituloEn: "Hardware diagnostics", rota: "/diagnostico", palavras: "diagnostico audio bluetooth modem diagnostics" },
  { titulo: "Serviços do sistema", tituloEn: "System services", rota: "/servicos", palavras: "servicos systemd boot ligar desligar services on off" },
  { titulo: "Kernel e módulos", tituloEn: "Kernel and modules", rota: "/kernel", palavras: "kernel modulo driver versao module version" },
  { titulo: "Memória por serviço", tituloEn: "Memory per service", rota: "/recursos", palavras: "memoria ram pss servico memory service" },
  { titulo: "Arquivo de configuração", tituloEn: "Configuration file", rota: "/config-arquivo", palavras: "config json arquivo file" },
  { titulo: "Ajuda", tituloEn: "Help", rota: "/ajuda", palavras: "ajuda duvida pergunta faq help question" },
]

export function normaliza(t: string) {
  return t
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
}
