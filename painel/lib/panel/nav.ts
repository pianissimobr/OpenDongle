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
  rota: string
}

export const CATEGORIAS: Categoria[] = [
  { id: "inicio", icon: "house", nome: "Início", rota: "/" },
  { id: "internet", icon: "globe", nome: "Internet", rota: "/internet" },
  { id: "perfil", icon: "user", nome: "Perfil", rota: "/perfil" },
  { id: "dispositivos", icon: "cable", nome: "Dispositivos", rota: "/dispositivos" },
  { id: "sistema", icon: "settings", nome: "Sistema", rota: "/sistema" },
]

export const CAT_AJUDA: Categoria = { id: "ajuda", icon: "help", nome: "Ajuda", rota: "/ajuda" }
export const CAT_AVANCADAS: Categoria = { id: "avancadas", icon: "wrench", nome: "Avançado", rota: "/avancadas" }

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

export type BuscaItem = { titulo: string; rota: string; palavras: string }

export const BUSCA: BuscaItem[] = [
  { titulo: "Início", rota: "/", palavras: "inicio home principal" },
  { titulo: "Perfil", rota: "/perfil", palavras: "perfil conta usuario senha avatar foto identidade" },
  { titulo: "Status e saúde", rota: "/status", palavras: "status saude cpu ram memoria disco temperatura" },
  { titulo: "Wi-Fi e hotspot", rota: "/hotspot", palavras: "wifi hotspot rede senha ssid" },
  { titulo: "Conectar a uma rede Wi-Fi", rota: "/wifi", palavras: "conectar wifi cliente rede casa" },
  { titulo: "Modem 4G", rota: "/modem", palavras: "4g chip sim operadora apn sinal modem" },
  { titulo: "LAN, DHCP e IP fixo", rota: "/rede", palavras: "lan dhcp ip fixo clientes aparelhos" },
  { titulo: "Firewall e portas", rota: "/firewall", palavras: "firewall porta redirecionar ssh bloquear" },
  { titulo: "Acesso remoto", rota: "/remoto", palavras: "remoto tailscale vpn longe acesso" },
  { titulo: "Navegação via Tor", rota: "/tor", palavras: "tor anonimo privacidade onion" },
  { titulo: "Bluetooth", rota: "/bluetooth", palavras: "bluetooth parear fone caixa teclado controle" },
  { titulo: "Aparelhos USB", rota: "/usb", palavras: "usb pendrive teclado placa som host otg" },
  { titulo: "Áudio", rota: "/audio", palavras: "audio som fone microfone volume mudo musica chamada" },
  { titulo: "LEDs", rota: "/leds", palavras: "led luz luzes piscar" },
  { titulo: "Conta e senha", rota: "/senha", palavras: "senha admin trocar password login entrar" },
  { titulo: "Data e hora", rota: "/hora", palavras: "data hora relogio fuso horario" },
  { titulo: "Atualizações", rota: "/atualizacoes", palavras: "atualizar atualizacao update sistema" },
  { titulo: "Espaço em disco", rota: "/espaco", palavras: "espaco disco cheio armazenamento liberar" },
  { titulo: "Desempenho", rota: "/desempenho", palavras: "desempenho cpu ram processos lento" },
  { titulo: "Hardware", rota: "/hardware", palavras: "hardware placa chip emmc imei mac" },
  { titulo: "Nome, backup e reset", rota: "/nome-backup", palavras: "nome backup reset fabrica" },
  { titulo: "Logs do sistema", rota: "/logs", palavras: "logs journalctl servico" },
  { titulo: "Diagnóstico de hardware", rota: "/diagnostico", palavras: "diagnostico audio bluetooth modem" },
  { titulo: "Serviços do sistema", rota: "/servicos", palavras: "servicos systemd boot ligar desligar" },
  { titulo: "Kernel e módulos", rota: "/kernel", palavras: "kernel modulo driver versao" },
  { titulo: "Memória por serviço", rota: "/recursos", palavras: "memoria ram pss servico" },
  { titulo: "Arquivo de configuração", rota: "/config-arquivo", palavras: "config json arquivo" },
  { titulo: "Ajuda", rota: "/ajuda", palavras: "ajuda duvida pergunta faq" },
]

export function normaliza(t: string) {
  return t
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
}
