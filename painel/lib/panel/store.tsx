"use client"

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { useRouter } from "next/navigation"
import { t } from "@/lib/panel/i18n"

/* ============================================================
   Tipos
   ============================================================ */

export type Severity = "info" | "success" | "warning" | "error"

export type Recomendacao = {
  id: string
  severity: Severity
  title: string
  description: string
  primary: { label: string; route: string }
  secondary: { label: string; route: string }[]
}

export type EstadoDongle = {
  rotulo: string
  modo: "hotspot" | "wifi" | "indefinido"
  internet: boolean
  ssidHotspot: string | null
  endereco: { ssid: string; ip: string; agora: boolean } | null
  primeiroUso: boolean
  redePendente: boolean
  tarefa: string | null
  recomendacao: Recomendacao | null
}

export type BtDevice = {
  mac: string
  nome: string
  tipo: string
  conectado?: boolean
  audio?: boolean
  bateria?: number | null
}

export type Servico = {
  nome: string
  habilitado: boolean
  rodando: boolean
  ramMb: number
  essencial: boolean
  gerenciado: string
  gerenciadoUrl: string
  aviso: string
}

/* ============================================================
   Estados do dongle (o seletor de debug alterna entre eles)
   ============================================================ */

export const ESTADOS: Record<string, EstadoDongle> = {
  normal: {
    rotulo: "Normal (hotspot com internet)",
    modo: "hotspot",
    internet: true,
    ssidHotspot: "OpenDongle",
    endereco: null,
    primeiroUso: false,
    redePendente: false,
    tarefa: null,
    recomendacao: null,
  },
  wifi_cliente: {
    rotulo: "Wi-Fi de casa conectado",
    modo: "wifi",
    internet: true,
    ssidHotspot: null,
    endereco: { ssid: "MinhaCasa", ip: "192.168.1.42", agora: true },
    primeiroUso: false,
    redePendente: false,
    tarefa: null,
    recomendacao: null,
  },
  hotspot_sem_internet: {
    rotulo: "Hotspot sem saída para internet",
    modo: "hotspot",
    internet: false,
    ssidHotspot: "OpenDongle",
    endereco: null,
    primeiroUso: false,
    redePendente: false,
    tarefa: null,
    recomendacao: {
      id: "hotspot_sem_saida",
      severity: "info",
      title: "O hotspot está funcionando, mas sem internet",
      description:
        "Os aparelhos conseguem se conectar ao dongle, mas ele ainda não tem uma conexão de saída.",
      primary: { label: "Configurar internet", route: "/internet" },
      secondary: [],
    },
  },
  wifi_sem_internet: {
    rotulo: "Wi-Fi de casa sem internet",
    modo: "wifi",
    internet: false,
    ssidHotspot: null,
    endereco: { ssid: "MinhaCasa", ip: "192.168.1.42", agora: true },
    primeiroUso: false,
    redePendente: false,
    tarefa: null,
    recomendacao: {
      id: "sem_internet_wifi",
      severity: "warning",
      title: "Sem internet",
      description:
        'O dongle está conectado na rede "MinhaCasa", mas não conseguiu acessar a internet.',
      primary: { label: "Verificar conexão", route: "/wifi" },
      secondary: [
        { label: "Trocar rede", route: "/wifi" },
        { label: "Voltar ao hotspot", route: "/hotspot" },
      ],
    },
  },
  primeiro_uso: {
    rotulo: "Primeiro uso (senha de fábrica)",
    modo: "hotspot",
    internet: true,
    ssidHotspot: "OpenDongle",
    endereco: null,
    primeiroUso: true,
    redePendente: false,
    tarefa: null,
    recomendacao: {
      id: "primeiro_uso",
      severity: "info",
      title: "Concluir a configuração inicial",
      description:
        "Ainda falta criar as credenciais de administração. Elas protegem o painel e permitem recuperar o acesso.",
      primary: { label: "Continuar", route: "/perfil" },
      secondary: [],
    },
  },
  rede_pendente: {
    rotulo: "Mudança de rede pendente",
    modo: "wifi",
    internet: true,
    ssidHotspot: null,
    endereco: { ssid: "MinhaCasa", ip: "192.168.1.42", agora: true },
    primeiroUso: false,
    redePendente: true,
    tarefa: null,
    recomendacao: {
      id: "confirmar_rede",
      severity: "warning",
      title: "Confirme a mudança de rede",
      description:
        "O dongle está acessível no endereço novo. Se você não confirmar, a mudança é desfeita em até 3 minutos.",
      primary: { label: "Manter configuração", route: "/confirmar" },
      secondary: [{ label: "Ver recuperação", route: "/ajuda" }],
    },
  },
  tarefa_andamento: {
    rotulo: "Instalação em andamento (Tor)",
    modo: "hotspot",
    internet: true,
    ssidHotspot: "OpenDongle",
    endereco: null,
    primeiroUso: false,
    redePendente: false,
    tarefa: "tor",
    recomendacao: null,
  },
}

/* ============================================================
   Dados mutáveis das telas internas
   ============================================================ */

export type MockData = {
  bluetooth: {
    ligado: boolean
    visivel: boolean
    nome: string
    mac: string
    buscando: boolean
    pareados: BtDevice[]
    novos: BtDevice[]
  }
  usb: {
    papel: "host" | "device"
    aparelhos: { tipo: string; nome: string; id: string }[]
  }
  audio: {
    bluetoothLigado: boolean
    placas: {
      id: string
      nome: string
      usb: boolean
      padrao: boolean
      controles: { nome: string; tipo: "saída" | "entrada"; volume: number; mudo: boolean }[]
    }[]
    btSaidas: { id: number; nome: string; padrao: boolean; volume: number; mudo: boolean }[]
    btEntradas: { id: number; nome: string; padrao: boolean; volume: number; mudo: boolean }[]
    btModos: Record<string, "musica" | "chamada">
  }
  modem: {
    presente: boolean
    simPresente: boolean
    registrado: boolean
    operadora: string
    rssiDbm: number
    modoOperacao: string
    imei: string
    firmwareOk: boolean
    diagnostico: string
  }
  lan: {
    ip: string
    prefixo: number
    dhcpInicio: number
    dhcpFim: number
    lease: string
    clientes: { mac: string; ip: string; nome: string; fixo: boolean }[]
    fixos: { mac: string; ip: string; nome: string }[]
  }
  firewall: {
    wifiClienteConfiavel: boolean
    sshPelaWan: boolean
    painelPelaWan: boolean
    redirecionamentos: {
      nome: string
      proto: string
      portaExterna: number
      ip: string
      portaInterna: number
    }[]
  }
  leds: Record<string, string>
  hostname: string
  servicos: Servico[]
  tor: { ativo: boolean }
  remoto: { ativo: boolean; lan: boolean; saida: boolean }
  hora: { automatica: boolean; fuso: string; agora: string }
}

function dadosIniciais(): MockData {
  return {
    bluetooth: {
      ligado: true,
      visivel: false,
      nome: "OpenDongle",
      mac: "AA:BB:CC:DD:EE:FF",
      buscando: false,
      pareados: [
        { mac: "F4:5E:AB:12:34:56", nome: "Fone do Lucas", tipo: "Fone", conectado: true, audio: true, bateria: 78 },
        { mac: "11:22:33:44:55:66", nome: "Caixa da Sala", tipo: "Caixa de som", conectado: false, audio: true, bateria: null },
      ],
      novos: [
        { mac: "AA:11:BB:22:CC:33", nome: "Fone BT-X2", tipo: "Fone", audio: true },
        { mac: "77:88:99:AA:BB:CC", nome: "Notebook Dell", tipo: "Computador", audio: false },
        { mac: "DE:AD:BE:EF:00:01", nome: "Controle Xbox", tipo: "Controle", audio: false },
      ],
    },
    usb: {
      papel: "host",
      aparelhos: [
        { tipo: "Armazenamento", nome: "SanDisk Ultra Fit", id: "0781:5583" },
        { tipo: "Teclado", nome: "Logitech K120", id: "046d:c31c" },
      ],
    },
    audio: {
      bluetoothLigado: true,
      placas: [
        {
          id: "Device",
          nome: "USB Audio Device",
          usb: true,
          padrao: true,
          controles: [
            { nome: "Speaker", tipo: "saída", volume: 65, mudo: false },
            { nome: "Mic", tipo: "entrada", volume: 40, mudo: false },
          ],
        },
      ],
      btSaidas: [{ id: 42, nome: "Fone do Lucas", padrao: false, volume: 80, mudo: false }],
      btEntradas: [{ id: 43, nome: "Fone do Lucas", padrao: false, volume: 50, mudo: false }],
      btModos: { "42": "musica", "43": "chamada" },
    },
    modem: {
      presente: true,
      simPresente: true,
      registrado: true,
      operadora: "Vivo",
      rssiDbm: -72,
      modoOperacao: "online",
      imei: "354289072345678",
      firmwareOk: true,
      diagnostico: "",
    },
    lan: {
      ip: "192.168.100.1",
      prefixo: 24,
      dhcpInicio: 10,
      dhcpFim: 99,
      lease: "12h",
      clientes: [
        { mac: "F4:5E:AB:12:34:56", ip: "192.168.100.10", nome: "celular-lucas", fixo: false },
        { mac: "11:22:33:44:55:66", ip: "192.168.100.11", nome: "notebook-trabalho", fixo: false },
        { mac: "AA:11:BB:22:CC:33", ip: "192.168.100.20", nome: "impressora-hp", fixo: true },
      ],
      fixos: [{ mac: "AA:11:BB:22:CC:33", ip: "192.168.100.20", nome: "impressora-hp" }],
    },
    firewall: {
      wifiClienteConfiavel: true,
      sshPelaWan: false,
      painelPelaWan: false,
      redirecionamentos: [
        { nome: "web-local", proto: "tcp", portaExterna: 8080, ip: "192.168.100.20", portaInterna: 80 },
        { nome: "ssh-pi", proto: "tcp", portaExterna: 2222, ip: "192.168.100.11", portaInterna: 22 },
      ],
    },
    leds: {
      "red:power": "auto",
      "green:wlan": "auto",
      "blue:wan": "auto",
    },
    tor: { ativo: false },
    remoto: { ativo: false, lan: false, saida: false },
    hora: { automatica: true, fuso: "America/Sao_Paulo", agora: "" },
    hostname: "opendongle",
    servicos: [
      { nome: "bluetooth.service", habilitado: true, rodando: true, ramMb: 4.2, essencial: false, gerenciado: "", gerenciadoUrl: "", aviso: "" },
      { nome: "avahi-daemon.service", habilitado: true, rodando: true, ramMb: 2.1, essencial: false, gerenciado: "", gerenciadoUrl: "", aviso: "Desligado, opendongle.local para de funcionar." },
      { nome: "cron.service", habilitado: true, rodando: true, ramMb: 1.0, essencial: false, gerenciado: "", gerenciadoUrl: "", aviso: "" },
      { nome: "tailscaled.service", habilitado: false, rodando: false, ramMb: 0.0, essencial: false, gerenciado: "Internet › Acesso remoto", gerenciadoUrl: "/remoto", aviso: "" },
      { nome: "pipewire.service", habilitado: false, rodando: false, ramMb: 0.0, essencial: false, gerenciado: "Dispositivos › Áudio", gerenciadoUrl: "/audio", aviso: "" },
      { nome: "opendongle.service", habilitado: true, rodando: true, ramMb: 8.5, essencial: true, gerenciado: "", gerenciadoUrl: "", aviso: "" },
      { nome: "dnsmasq.service", habilitado: true, rodando: true, ramMb: 2.8, essencial: true, gerenciado: "", gerenciadoUrl: "", aviso: "" },
      { nome: "hostapd@wlan0.service", habilitado: true, rodando: true, ramMb: 3.1, essencial: true, gerenciado: "", gerenciadoUrl: "", aviso: "" },
    ],
  }
}

/* ============================================================
   Perfil
   ============================================================ */

// Atualizado pela API depois do primeiro fetch; começa vazio pra não mostrar
// um nome fixo antes de saber quem administra o dongle.
export const PERFIL = { nome: "", usuario: "", admin: true, foto: false }

export function saudacao() {
  const nome = PERFIL.nome || PERFIL.usuario
  const primeiro = nome.split(" ")[0] || t("visitante", "there")
  const hora = new Date().getHours()
  if (hora < 12) return t(`Bom dia, ${primeiro}`, `Good morning, ${primeiro}`)
  if (hora < 18) return t(`Boa tarde, ${primeiro}`, `Good afternoon, ${primeiro}`)
  return t(`Boa noite, ${primeiro}`, `Good evening, ${primeiro}`)
}

/* ============================================================
   Saúde simulada
   ============================================================ */

export type Saude = { ramPct: number; tempC: number; discoPct: number }

export function saudeMock(): Saude {
  const t = Date.now() / 1000
  let ram = 62 + 12 * Math.sin(t / 20) + 3 * Math.sin(t / 3)
  ram = Math.max(10, Math.min(95, ram))
  let temp = 46 + 6 * Math.sin(t / 30) + 2 * Math.sin(t / 5)
  temp = Math.max(35, Math.min(78, temp))
  return { ramPct: Math.round(ram), tempC: Math.round(temp), discoPct: 34 }
}

/* ============================================================
   Overlay de processamento
   ============================================================ */

type Overlay = { ativo: boolean; mensagem: string; detalhe: string; duracao: number } | null

/* ============================================================
   Contexto
   ============================================================ */

type Ctx = {
  estadoNome: string
  estado: EstadoDongle
  setEstado: (n: string) => void
  avancadas: boolean
  setAvancadas: (v: boolean) => void
  dados: MockData
  setDados: (fn: (d: MockData) => MockData) => void
  overlay: Overlay
  /** Mostra o overlay por `duracao` ms, executa a mutação e navega. */
  processar: (opts: {
    mensagem: string
    detalhe?: string
    duracao?: number
    mutar?: (d: MockData) => MockData
    depois?: () => void
    ir?: string
    setEstado?: string
    /** ação real no motor (opendongle_engine.executar); ex.: "bt-conectar" */
    acao?: string
    args?: Record<string, unknown>
  }) => Promise<ResultadoAcao | undefined>
  /** Recarrega estado/dados/saúde do dongle. */
  recarregar: () => Promise<void>
  saude: Saude
}

const PanelCtx = createContext<Ctx | null>(null)

type ApiTudo = {
  estado: EstadoDongle
  saude: Saude
  dados: MockData
  perfil: { nome: string; usuario: string; admin: boolean }
}

export async function apiGet<T>(rota: string): Promise<T | null> {
  try {
    const r = await fetch(rota, { cache: "no-store", credentials: "same-origin" })
    if (r.status === 401) {
      // sem sessão: manda pra tela de login (a menos que já esteja nela)
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login"))
        window.location.href = "/login"
      return null
    }
    if (!r.ok) return null
    return (await r.json()) as T
  } catch {
    return null
  }
}

/** POST de uma ação para o motor (opendongle_engine.executar). */
/** Resposta do motor a uma ação: ok, e às vezes erro/aviso e dados extras. */
export type ResultadoAcao = { ok: boolean; erro?: string; aviso?: string; [k: string]: unknown }

export async function apiAcao(acao: string, args: Record<string, unknown>): Promise<ResultadoAcao> {
  try {
    const r = await fetch("/api/acao", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ acao, args }),
    })
    if (r.status === 401) {
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login"))
        window.location.href = "/login"
      return { ok: false, erro: "sessão expirada" }
    }
    return await r.json()
  } catch (e) {
    return { ok: false, erro: String(e) }
  }
}

export function PanelProvider({ children }: { children: ReactNode }) {
  const router = useRouter()
  const [estadoNome, setEstadoNome] = useState("normal")
  const [avancadas, setAvancadas] = useState(false)
  const [dados, setDadosState] = useState<MockData>(dadosIniciais)
  const [overlay, setOverlay] = useState<Overlay>(null)
  const [saude, setSaude] = useState<Saude>(saudeMock)
  // estado real do dongle; começa no mock só pra primeira pintura não vir vazia
  const [estadoReal, setEstadoReal] = useState<EstadoDongle | null>(null)
  const overlayTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Recarrega tudo do dongle. Chamado no início e depois de cada ação.
  const recarregar = async () => {
    const t = await apiGet<ApiTudo>("/api/tudo")
    if (!t) return
    setEstadoReal(t.estado)
    setDadosState(t.dados)
    setSaude(t.saude)
    if (t.perfil) {
      PERFIL.nome = t.perfil.nome
      PERFIL.usuario = t.perfil.usuario
      PERFIL.admin = t.perfil.admin
      PERFIL.foto = !!(t.perfil as { foto?: boolean }).foto
    }
  }

  useEffect(() => {
    (async () => {
      const c = await apiGet<{ primeiroUso: boolean; logado: boolean }>("/api/contexto")
      const aqui = window.location.pathname
      if (c?.primeiroUso) {
        if (!aqui.startsWith("/cadastro")) window.location.href = "/cadastro"
        return
      }
      if (c && !c.logado) {
        if (!aqui.startsWith("/login")) window.location.href = "/login"
        return
      }
      recarregar()
    })()
  }, [])

  // Saúde ao vivo: leve o bastante pra pedir a cada 5 s. Para quando a aba sai
  // da frente e desiste depois de ~10 min parada — o painel dorme por RAM e uma
  // aba esquecida não pode segurar o dongle acordado.
  useEffect(() => {
    let paradas = 0
    const acordar = () => { paradas = 0 }
    ;["pointerdown", "keydown", "focus"].forEach((e) =>
      window.addEventListener(e, acordar, { passive: true }))
    const id = setInterval(async () => {
      if (document.hidden) return
      if (++paradas > 120) { clearInterval(id); return }
      const s = await apiGet<Saude>("/api/saude")
      if (s) setSaude(s)
    }, 5000)
    return () => {
      clearInterval(id)
      ;["pointerdown", "keydown", "focus"].forEach((e) => window.removeEventListener(e, acordar))
    }
  }, [])

  const setDados = (fn: (d: MockData) => MockData) => setDadosState((d) => fn(d))

  const processar: Ctx["processar"] = ({ mensagem, detalhe = "", duracao, mutar, depois, ir, setEstado, acao, args }) =>
    new Promise<ResultadoAcao | undefined>((resolve) => {
      const estimativa = Math.max(duracao ?? 3000, 700)
      setOverlay({ ativo: true, mensagem, detalhe, duracao: estimativa })
      const finalizar = async () => {
        if (mutar) setDadosState((d) => mutar(d))     // otimista: resposta imediata
        let res: ResultadoAcao | undefined
        if (acao) {
          res = await apiAcao(acao, args ?? {})        // ação real no motor
          await recarregar()                           // e o estado verdadeiro por cima
        }
        if (setEstado) setEstadoNome(setEstado)
        if (depois) depois()
        setOverlay(null)
        if (ir) router.push(ir)
        resolve(res)
      }
      // ação real: espera o servidor. Sem ação (só navegação): tempo curto do protótipo.
      if (acao) {
        finalizar()
      } else {
        if (overlayTimer.current) clearTimeout(overlayTimer.current)
        overlayTimer.current = setTimeout(finalizar, Math.min(estimativa, 1200))
      }
    })

  const value = useMemo<Ctx>(
    () => ({
      estadoNome,
      estado: estadoReal ?? ESTADOS[estadoNome],
      setEstado: setEstadoNome,
      avancadas,
      setAvancadas,
      dados,
      setDados,
      overlay,
      processar,
      recarregar,
      saude,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [estadoNome, estadoReal, avancadas, dados, overlay, saude],
  )

  return <PanelCtx.Provider value={value}>{children}</PanelCtx.Provider>
}

export function usePanel() {
  const ctx = useContext(PanelCtx)
  if (!ctx) throw new Error("usePanel deve ser usado dentro de PanelProvider")
  return ctx
}
