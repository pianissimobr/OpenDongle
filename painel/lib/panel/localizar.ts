/**
 * Localizador do dongle, versão navegador do opendongle_localizar.py.
 *
 * Depois de o dongle trocar o hotspot por um Wi-Fi da casa, a página (já
 * carregada no celular) perde o servidor de onde veio. Ela não consegue mandar
 * o broadcast UDP do localizador de PC, então faz o equivalente por HTTP:
 * testa endereços prováveis em /api/ola e confere a identidade que o dongle
 * mostrou antes de cair — com cinco dongles na mesma rede, achar "um" não basta.
 *
 * Ordem: o IP da última vez nessa rede (com o lease fixo, quase sempre o
 * mesmo), os nomes .local (mDNS), e por fim uma varredura das faixas
 * domésticas, começando pela que tem um roteador respondendo.
 */

export type Achado = { ip: string; host: string }
export type Progresso = (texto: string) => void

const TEMPO_PROBE_MS = 1500
const TEMPO_ROTEADOR_MS = 900
// recusa (RST) chega em milissegundos; faixa inexistente só falha no prazo
const RECUSA_RAPIDA_MS = 300
const PARALELO = 64

// faixas mais comuns em roteadores domésticos no Brasil (Vivo usa .15)
const FAIXAS_COMUNS = [
  "192.168.0", "192.168.1", "192.168.15", "192.168.2", "192.168.3",
  "192.168.10", "192.168.25", "192.168.43", "192.168.5", "192.168.8",
  "192.168.88", "10.0.0", "10.0.1", "10.1.1", "172.16.0",
]

async function comPrazo(url: string, ms: number, init: RequestInit = {}): Promise<Response> {
  const ctl = new AbortController()
  const t = setTimeout(() => ctl.abort(), ms)
  try {
    return await fetch(url, { ...init, cache: "no-store", signal: ctl.signal })
  } finally {
    clearTimeout(t)
  }
}

/** true só se ali responde ESTE dongle (mesmo id). */
async function eOMeu(host: string, id: string): Promise<boolean> {
  try {
    const r = await comPrazo(`http://${host}/api/ola`, TEMPO_PROBE_MS)
    if (!r.ok) return false
    const d = await r.json()
    return d?.tipo === "OPENDONGLE_HELLO_V1" && d?.id === id
  } catch {
    return false
  }
}

/** Testa uma lista de endereços em paralelo (limitado); para no primeiro achado. */
async function varrer(hosts: string[], id: string, parar: () => boolean): Promise<string | null> {
  let achado: string | null = null
  let i = 0
  const trabalhador = async () => {
    while (!achado && !parar() && i < hosts.length) {
      const h = hosts[i++]
      if (await eOMeu(h, id)) achado = h
    }
  }
  await Promise.all(Array.from({ length: Math.min(PARALELO, hosts.length) }, trabalhador))
  return achado
}

/**
 * Põe na frente as faixas onde há um roteador, a mais rápida primeiro: é a
 * rede em que o celular está. Um roteador existe se responde OU recusa a
 * conexão depressa — muitos não têm página na porta 80 e só devolvem RST
 * (visto: 192.168.5.1 recusando em 1,4 ms). Faixa que não existe estoura o
 * prazo. Um modem um salto acima (o da operadora, em rede com NAT duplo)
 * também aparece, mas mais lento, e fica depois.
 */
async function faixasVivas(faixas: string[]): Promise<string[]> {
  const tempo = new Map<string, number>()
  const marca = (f: string, ms: number) => tempo.set(f, Math.min(ms, tempo.get(f) ?? Infinity))
  await Promise.all(faixas.flatMap((f) => [".1", ".254"].map(async (fim) => {
    const t0 = performance.now()
    try {
      // no-cors: não dá pra ler a resposta, mas se resolveu, há um servidor ali
      await comPrazo(`http://${f}${fim}/`, TEMPO_ROTEADOR_MS, { mode: "no-cors" })
      marca(f, performance.now() - t0)
    } catch {
      const ms = performance.now() - t0
      if (ms < RECUSA_RAPIDA_MS) marca(f, ms)     // recusou: tem alguém ali
    }
  })))
  return faixas.filter((f) => tempo.has(f)).sort((x, y) => tempo.get(x)! - tempo.get(y)!)
}

const faixaDe = (ip: string) => ip.split(".").slice(0, 3).join(".")

export async function localizarDongle(opts: {
  id: string
  ipProvavel?: string          // IP da última vez nessa mesma rede
  ipsConhecidos?: string[]     // IPs de outras redes onde já esteve (dão faixas prováveis)
  hostname?: string
  progresso?: Progresso
  cancelado?: () => boolean
}): Promise<Achado | null> {
  const { id, ipProvavel, ipsConhecidos = [], hostname, progresso = () => {}, cancelado = () => false } = opts
  if (!id) return null
  const achou = (ip: string): Achado => ({ ip, host: `http://${ip}` })

  // 1) palpites diretos, todos de uma vez
  const nomes = [...new Set([hostname && `${hostname}.local`, "opendongle.local"].filter(Boolean) as string[])]
  const diretos = [...(ipProvavel ? [ipProvavel] : []), ...nomes]
  progresso(ipProvavel ? `Testando o endereço da última vez (${ipProvavel})…` : "Procurando pelo nome na rede…")
  const direto = await varrer(diretos, id, cancelado)
  if (direto) return achou(direto)

  // 2) varredura das faixas, a do roteador que responde primeiro
  const faixas = [...new Set([
    ...(ipProvavel ? [faixaDe(ipProvavel)] : []),
    ...ipsConhecidos.map(faixaDe),
    ...FAIXAS_COMUNS,
  ])]
  progresso("Descobrindo a faixa de endereços desta rede…")
  // o dongle está na mesma rede que o aparelho: só as faixas com roteador
  // interessam. Se nenhum roteador se mostrou, varre todas (mais lento).
  const vivas = await faixasVivas(faixas)
  const ordem = vivas.length ? vivas : faixas
  for (const f of ordem) {
    if (cancelado()) return null
    progresso(`Procurando em ${f}.x…`)
    const hosts = Array.from({ length: 254 }, (_, k) => `${f}.${k + 1}`)
    const ip = await varrer(hosts, id, cancelado)
    if (ip) return achou(ip)
  }
  return null
}
