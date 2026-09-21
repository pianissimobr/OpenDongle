"use client"

import { useState, useEffect, useRef } from "react"
import { Wifi, SignalHigh, SignalMedium, SignalLow, Lock, RefreshCw, History, Keyboard, Search, CircleCheck, ExternalLink } from "lucide-react"
import { PageHeader, Card, CardTitle, Field, Input, Btn, Notice, Pill, Msg } from "@/components/panel/ui"
import { usePanel, apiAcao } from "@/lib/panel/store"
import { localizarDongle, type Achado } from "@/lib/panel/localizar"
import { t } from "@/lib/panel/i18n"
import { cn } from "@/lib/utils"

type Rede = { ssid: string; sinal: number; aberta: boolean; seguranca: string }
type UltimaConexao = { ssid: string; ok: boolean; detalhe: string; quando: number } | null
type Busca = {
  redes?: Rede[]; salvas?: string[]; emHotspot?: boolean; aviso?: string
  quando?: number; buscando?: boolean; agora?: number
  id?: string; enderecos?: Record<string, string>; ultimaConexao?: UltimaConexao
}
/** o que vai ser conectado: da lista, de uma rede salva ou digitado */
type Escolha = { ssid: string; aberta?: boolean; salva?: boolean; manual?: boolean }
type Fase = "lista" | "confirmarBusca" | "buscando" | "confirmarConexao" | "trocando"

const dorme = (ms: number) => new Promise((r) => setTimeout(r, ms))
// quem está no hotspot precisa reconectar à mão: dá tempo de sobra
const ESPERA_BUSCA_MS = 3 * 60 * 1000

/** GET da busca. null quando a rede caiu (esperado enquanto o hotspot está fora). */
async function lerBusca(): Promise<Busca | null> {
  try {
    const r = await fetch("/api/wifi-scan", { cache: "no-store", credentials: "same-origin" })
    if (r.status === 401) { window.location.href = "/login"; return null }
    return r.ok ? await r.json() : null
  } catch { return null }
}

function haQuanto(segundos: number) {
  const m = Math.floor(segundos / 60)
  if (segundos < 60) return t("agora mesmo", "just now")
  if (m < 60) return m === 1 ? t("há 1 minuto", "1 minute ago") : t(`há ${m} minutos`, `${m} minutes ago`)
  const h = Math.floor(m / 60)
  return h === 1 ? t("há 1 hora", "1 hour ago") : t(`há ${h} horas`, `${h} hours ago`)
}

function IconeSinal({ s }: { s: number }) {
  if (s >= 66) return <SignalHigh className="size-4.5 text-ok" />
  if (s >= 40) return <SignalMedium className="size-4.5 text-warn" />
  return <SignalLow className="size-4.5 text-muted-foreground" />
}

function Passos({ itens }: { itens: React.ReactNode[] }) {
  return (
    <ol className="space-y-2.5">
      {itens.map((item, i) => (
        <li key={i} className="flex gap-3 text-sm">
          <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">{i + 1}</span>
          <span className="pt-0.5">{item}</span>
        </li>
      ))}
    </ol>
  )
}

export default function WifiPage() {
  const { estado, dados } = usePanel()
  const hotspot = estado.ssidHotspot || "OpenDongle"
  const [b, setB] = useState<Busca>({})
  const [fase, setFase] = useState<Fase>("lista")
  const [carregando, setCarregando] = useState(true)
  const [sel, setSel] = useState<Escolha | null>(null)
  const [senha, setSenha] = useState("")
  const [aviso, setAviso] = useState("")
  // troca de rede em andamento
  const [destino, setDestino] = useState("")
  const [resposta, setResposta] = useState<{ ok: boolean; ip?: string; erro?: string } | null>(null)
  const [procurando, setProcurando] = useState(false)
  const [progresso, setProgresso] = useState("")
  const [achado, setAchado] = useState<Achado | null | undefined>(undefined)
  const cancelar = useRef(false)

  const redes = b.redes ?? []
  const salvas = b.salvas ?? []
  const idade = b.quando ? (b.agora ?? 0) - b.quando : -1

  const carregar = async () => {
    setCarregando(true)
    const d = await lerBusca()
    if (d) setB(d); else setAviso(t("Não foi possível ler as redes.", "Could not read the networks."))
    setCarregando(false)
  }
  useEffect(() => { carregar(); return () => { cancelar.current = true } }, [])

  // ---- Buscar: em hotspot, o dongle pausa o hotspot pra poder escanear
  const pedirBusca = () => {
    setAviso("")
    if (b.emHotspot) setFase("confirmarBusca")
    else carregar()                     // em modo cliente o scan é direto
  }
  const buscarAgora = async () => {
    const anterior = b.quando ?? 0
    setFase("buscando")
    await apiAcao("wifi-buscar", {})   // pode nem voltar: o hotspot cai logo depois
    const limite = Date.now() + ESPERA_BUSCA_MS
    while (Date.now() < limite && !cancelar.current) {
      await dorme(2000)
      const d = await lerBusca()
      if (d && d.quando && d.quando !== anterior && !d.buscando) {
        setB(d); setFase("lista"); return
      }
    }
    setFase("lista")
    setAviso(t(`A lista não chegou. Confira se este aparelho voltou para o Wi-Fi "${hotspot}" e toque em Buscar de novo.`,
               `The list did not arrive. Check that this device is back on the "${hotspot}" Wi-Fi and tap Scan again.`))
  }

  // ---- Conectar
  const escolher = (e: Escolha) => { setSel(e); setSenha(""); setFase("lista") }
  const salva = !!sel && (sel.salva || salvas.includes(sel.ssid))
  // senha: obrigatória numa rede protegida que o dongle ainda não conhece;
  // na salva, em branco reaproveita a guardada; digitada, pode ser aberta
  const precisaSenha = !!sel && !sel.aberta && !salva && !sel.manual
  const senhaCurta = senha.length > 0 && senha.length < 8
  const pode = !!sel?.ssid.trim() && !senhaCurta && (!precisaSenha || senha.length > 0)

  const conectarAgora = async () => {
    if (!sel) return
    const ssid = sel.ssid.trim()
    setDestino(ssid); setResposta(null); setAchado(undefined); setProgresso("")
    setFase("trocando")
    // Quem está no hotspot (ou no Wi-Fi atual do dongle) perde esta resposta:
    // a conexão cai assim que o dongle troca de rede. Pelo cabo USB ela chega.
    try {
      const r = await fetch("/api/acao", {
        method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
        body: JSON.stringify({ acao: "connect-wifi", args: { ssid, senha } }),
      })
      const d = await r.json()
      setResposta({ ok: !!d.ok, ip: d.ip, erro: d.erro })
      if (d.ok && d.ip) setAchado({ ip: d.ip, host: `http://${d.ip}` })
    } catch { /* conexão caiu: é o esperado — segue pelo localizador */ }
  }

  const encontrar = async () => {
    setProcurando(true); setAchado(undefined)
    const r = await localizarDongle({
      id: b.id ?? "",
      ipProvavel: b.enderecos?.[destino],
      ipsConhecidos: Object.values(b.enderecos ?? {}),
      hostname: dados.hostname,
      progresso: setProgresso,
      cancelado: () => cancelar.current,
    })
    setAchado(r); setProcurando(false)
  }

  const itemLista = (chave: string, ativo: boolean, onClick: () => void, conteudo: React.ReactNode) => (
    <button key={chave} onClick={onClick}
      className={cn("flex w-full items-center gap-3 rounded-lg px-2.5 py-3 text-left transition-colors hover:bg-muted", ativo && "bg-muted")}>
      {conteudo}
    </button>
  )

  const ult = b.ultimaConexao
  const falhaRecente = ult && !ult.ok && (b.agora ?? 0) - ult.quando < 30 * 60

  // ======================= troca de rede em andamento
  if (fase === "trocando") {
    const falhou = resposta && !resposta.ok
    return (
      <div className="space-y-6">
        <PageHeader icon={Wifi} title={t(`Conectando a "${destino}"`, `Connecting to "${destino}"`)} />
        <Card className="mx-auto max-w-xl">
          {falhou ? (
            <div className="space-y-4">
              <Msg tone="err">{resposta.erro || t("Não conectou.", "It did not connect.")}</Msg>
              <Btn variant="secondary" onClick={() => { setFase("lista"); carregar() }}>{t("Voltar às redes", "Back to networks")}</Btn>
            </div>
          ) : achado ? (
            <div className="space-y-4 text-center">
              <CircleCheck className="mx-auto size-10 text-ok" />
              <p className="text-sm text-muted-foreground">{t(`Seu dongle está na rede "${destino}" em`, `Your dongle is on "${destino}" at`)}</p>
              <p className="font-mono text-2xl font-semibold">{achado.host.replace("http://", "")}</p>
              <a href={`${achado.host}/`} className="inline-block"><Btn variant="primary"><ExternalLink className="size-4" /> {t("Abrir o painel", "Open the panel")}</Btn></a>
              <p className="text-xs text-muted-foreground">{t("Guarde esse endereço nos favoritos. Você vai precisar entrar de novo com a sua senha.", "Bookmark this address. You will need to sign in again with your password.")}</p>
            </div>
          ) : (
            <div className="space-y-5">
              <Passos itens={[
                t(`O dongle está desligando o hotspot e entrando na rede "${destino}". A sua conexão com ele cai agora.`,
                  `The dongle is turning off the hotspot and joining "${destino}". Your connection to it drops now.`),
                t(`Conecte este aparelho à mesma rede "${destino}".`, `Connect this device to the same network "${destino}".`),
                t("Toque em Encontrar meu dongle.", "Tap Find my dongle."),
              ]} />
              <Btn variant="primary" className="w-full" onClick={encontrar} disabled={procurando}>
                {procurando ? <RefreshCw className="size-4 animate-spin" /> : <Search className="size-4" />}
                {procurando ? (progresso || t("Procurando…", "Searching…")) : t("Encontrar meu dongle", "Find my dongle")}
              </Btn>
              {achado === null && (
                <Notice>
                  <span className="block font-medium">{t("Não achei o dongle nesta rede.", "I could not find the dongle on this network.")}</span>
                  <span className="mt-1.5 block">{t(`• Se a senha estava errada, o dongle volta sozinho para o hotspot "${hotspot}" em cerca de 1 minuto — conecte-se a ele e abra esta página de novo.`,
                    `• If the password was wrong, the dongle goes back to the "${hotspot}" hotspot on its own in about 1 minute — connect to it and open this page again.`)}</span>
                  <span className="mt-1 block">{t("• Confira se este aparelho está mesmo na rede escolhida e toque em Encontrar de novo.", "• Make sure this device is really on the chosen network and tap Find again.")}</span>
                  <span className="mt-1 block">{t("• Redes com endereços fora do comum: rode o opendongle_localizar.py num computador da mesma rede, ou veja a lista de aparelhos no roteador.", "• Networks with unusual addressing: run opendongle_localizar.py on a computer on the same network, or check the device list on the router.")}</span>
                </Notice>
              )}
            </div>
          )}
        </Card>
      </div>
    )
  }

  // ======================= lista
  return (
    <div className="space-y-6">
      <PageHeader
        icon={Wifi}
        title={t("Conectar a uma rede Wi-Fi", "Connect to a Wi-Fi network")}
        desc={t("Use uma rede existente (como o Wi-Fi de casa) para dar internet ao dongle.",
                "Use an existing network (like your home Wi-Fi) to give the dongle internet.")}
      >
        <Btn size="sm" variant="ghost" onClick={pedirBusca} disabled={carregando || fase === "buscando"}>
          <RefreshCw className={cn("size-4", (carregando || fase === "buscando") && "animate-spin")} /> {t("Buscar", "Scan")}
        </Btn>
      </PageHeader>

      {falhaRecente && (
        <Notice>{t(`A última tentativa de conectar a "${ult.ssid}" não deu certo: ${ult.detalhe}. O dongle voltou para o hotspot.`,
                   `The last attempt to connect to "${ult.ssid}" failed: ${ult.detalhe}. The dongle went back to the hotspot.`)}</Notice>
      )}

      {fase === "confirmarBusca" && (
        <Card>
          <CardTitle>{t("Antes de buscar", "Before scanning")}</CardTitle>
          <Passos itens={[
            t("A varredura de Wi-Fi vai acontecer e você vai perder a conexão com o dongle por alguns segundos.",
              "The Wi-Fi scan will run and you will lose the connection to the dongle for a few seconds."),
            t(`Daqui a alguns segundos, conecte-se de novo ao Wi-Fi "${hotspot}".`, `In a few seconds, connect again to the "${hotspot}" Wi-Fi.`),
            t("Volte a esta página: a lista nova aparece sozinha, e você escolhe a rede e insere a senha.",
              "Come back to this page: the new list shows up on its own, then pick the network and enter the password."),
          ]} />
          <div className="mt-5 flex flex-wrap gap-2">
            <Btn variant="primary" onClick={buscarAgora}>{t("Entendi, buscar", "Got it, scan")}</Btn>
            <Btn variant="ghost" onClick={() => setFase("lista")}>{t("Cancelar", "Cancel")}</Btn>
          </div>
        </Card>
      )}

      {fase === "buscando" && (
        <Notice tone="info">
          <span className="flex items-start gap-2"><RefreshCw className="mt-0.5 size-4 shrink-0 animate-spin" />
            {t(`Buscando redes… Se você estava no hotspot, conecte-se de novo ao Wi-Fi "${hotspot}". Esta página atualiza sozinha.`,
               `Scanning… If you were on the hotspot, connect again to the "${hotspot}" Wi-Fi. This page updates on its own.`)}</span>
        </Notice>
      )}

      {aviso && <Msg tone="err">{aviso}</Msg>}

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="space-y-6 lg:col-span-3">
          <Card>
            <CardTitle hint={carregando ? t("carregando…", "loading…") : t(`${redes.length} redes`, `${redes.length} networks`)}>
              {t("Redes disponíveis", "Available networks")}
            </CardTitle>
            {!carregando && (
              <p className="-mt-2 pb-2 text-xs text-muted-foreground">
                {idade >= 0
                  ? t(`Último escaneamento ${haQuanto(idade)}.`, `Last scan ${haQuanto(idade)}.`)
                  : t("Ainda não há varredura. Toque em Buscar.", "No scan yet. Tap Scan.")}
              </p>
            )}
            {!carregando && redes.length === 0 && idade >= 0 && (
              <p className="py-3 text-sm text-muted-foreground">{b.aviso || t("Nenhuma rede encontrada por perto.", "No networks found nearby.")}</p>
            )}
            <div className="-mx-1 divide-y divide-border">
              {redes.map((r) => itemLista(r.ssid, sel?.ssid === r.ssid && !sel.manual, () => escolher({ ssid: r.ssid, aberta: r.aberta }), <>
                <IconeSinal s={r.sinal} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{r.ssid}</span>
                  <span className="text-xs text-muted-foreground">{t(`${r.sinal}% de sinal`, `${r.sinal}% signal`)}{salvas.includes(r.ssid) ? t(" · salva", " · saved") : ""}</span>
                </span>
                {r.aberta ? <Pill tone="warn">{t("Aberta", "Open")}</Pill> : <Lock className="size-3.5 text-muted-foreground" />}
              </>))}
            </div>
            <div className="mt-3 border-t border-border pt-3">
              {itemLista("manual", !!sel?.manual, () => escolher({ ssid: "", manual: true }), <>
                <Keyboard className="size-4.5 text-muted-foreground" />
                <span className="text-sm font-medium">{t("Digitar o nome da rede", "Type the network name")}</span>
              </>)}
            </div>
          </Card>

          {salvas.length > 0 && (
            <Card>
              <CardTitle hint={t("reconecta sem digitar a senha", "reconnects without typing the password")}>{t("Redes salvas", "Saved networks")}</CardTitle>
              <div className="-mx-1 divide-y divide-border">
                {salvas.map((ssid) => itemLista("salva-" + ssid, sel?.ssid === ssid && !!sel.salva, () => escolher({ ssid, salva: true }), <>
                  <History className="size-4.5 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">{ssid}</span>
                </>))}
              </div>
            </Card>
          )}
        </div>

        <Card className="h-fit lg:col-span-2">
          <CardTitle>{sel?.manual ? t("Rede digitada", "Typed network") : sel ? t(`Conectar a "${sel.ssid}"`, `Connect to "${sel.ssid}"`) : t("Selecione uma rede", "Select a network")}</CardTitle>
          {!sel ? (
            <p className="text-sm text-muted-foreground">{t("Escolha uma rede da lista, uma rede salva, ou digite o nome.", "Pick a network from the list, a saved one, or type the name.")}</p>
          ) : fase === "confirmarConexao" ? (
            <div className="space-y-5">
              <Passos itens={[
                t(`O dongle vai derrubar a sua rede: ele desliga o hotspot e entra em "${sel.ssid.trim()}".`,
                  `The dongle will drop your network: it turns off the hotspot and joins "${sel.ssid.trim()}".`),
                t(`Conecte este aparelho à mesma rede "${sel.ssid.trim()}".`, `Connect this device to the same network "${sel.ssid.trim()}".`),
                t("Toque em Encontrar meu dongle para ver o endereço dele.", "Tap Find my dongle to see its address."),
              ]} />
              <div className="flex flex-wrap gap-2">
                <Btn variant="primary" onClick={conectarAgora}>{t("Conectar", "Connect")}</Btn>
                <Btn variant="ghost" onClick={() => setFase("lista")}>{t("Voltar", "Back")}</Btn>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {sel.manual && (
                <Field label={t("Nome da rede (SSID)", "Network name (SSID)")} hint={t("Exatamente como aparece no celular, com maiúsculas.", "Exactly as it shows on your phone, including capitals.")}>
                  <Input value={sel.ssid} onChange={(e) => setSel({ ...sel, ssid: e.target.value })} maxLength={32} autoFocus />
                </Field>
              )}
              {!sel.aberta && (
                <Field label={t("Senha da rede", "Network password")}
                  hint={senhaCurta ? t("A senha de Wi-Fi tem pelo menos 8 caracteres.", "Wi-Fi passwords have at least 8 characters.")
                    : salva ? t("Deixe em branco para usar a senha salva.", "Leave blank to use the saved password.")
                    : sel.manual ? t("Deixe em branco se a rede for aberta.", "Leave blank if the network is open.") : undefined}>
                  <Input type="password" value={senha} onChange={(e) => setSenha(e.target.value)} autoFocus={!sel.manual} />
                </Field>
              )}
              <p className="text-xs text-muted-foreground">
                {t("Se a senha estiver errada, o dongle volta sozinho para o hotspot em cerca de 1 minuto.",
                   "If the password is wrong, the dongle goes back to the hotspot on its own in about 1 minute.")}
              </p>
              <Btn variant="primary" onClick={() => setFase("confirmarConexao")} className="w-full" disabled={!pode}>
                {t("Continuar", "Continue")}
              </Btn>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
