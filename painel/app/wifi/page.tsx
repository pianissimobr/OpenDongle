"use client"

import { useState, useEffect } from "react"
import { Wifi, SignalHigh, SignalMedium, SignalLow, Lock, RefreshCw } from "lucide-react"
import { PageHeader, Card, CardTitle, Field, Input, Btn, Notice, Pill } from "@/components/panel/ui"
import { usePanel } from "@/lib/panel/store"
import { t } from "@/lib/panel/i18n"
import { cn } from "@/lib/utils"

type Rede = { ssid: string; sinal: number; seguranca: string }

function IconeSinal({ s }: { s: number }) {
  if (s >= 66) return <SignalHigh className="size-4.5 text-ok" />
  if (s >= 40) return <SignalMedium className="size-4.5 text-warn" />
  return <SignalLow className="size-4.5 text-muted-foreground" />
}

export default function WifiPage() {
  const { processar } = usePanel()
  const [sel, setSel] = useState<Rede | null>(null)
  const [senha, setSenha] = useState("")
  const [redes, setRedes] = useState<Rede[]>([])
  const [aviso, setAviso] = useState("")
  const [buscando, setBuscando] = useState(true)

  const buscar = async () => {
    setBuscando(true)
    try {
      const r = await fetch("/api/wifi-scan", { cache: "no-store", credentials: "same-origin" })
      if (r.status === 401) { window.location.href = "/login"; return }
      const d = await r.json()
      setRedes(d.redes || [])
      setAviso(d.aviso || "")
    } catch { setAviso(t("Não foi possível buscar redes.", "Could not scan for networks.")) }
    setBuscando(false)
  }
  useEffect(() => { buscar() }, [])

  const conectar = async () => {
    if (!sel) return
    await processar({
      mensagem: t(`Conectando a "${sel.ssid}"`, `Connecting to "${sel.ssid}"`),
      detalhe: t("O dongle vai testar a conexão antes de confirmar.", "The dongle will test the connection before confirming."),
      duracao: 30000,
      acao: "connect-wifi",
      args: { ssid: sel.ssid, senha },
      ir: "/confirmar",
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader
        icon={Wifi}
        title={t("Conectar a uma rede Wi-Fi", "Connect to a Wi-Fi network")}
        desc={t("Use uma rede existente (como o Wi-Fi de casa) para dar internet ao dongle.",
                "Use an existing network (like your home Wi-Fi) to give the dongle internet.")}
      >
        <Btn size="sm" variant="ghost" onClick={buscar} disabled={buscando}>
          <RefreshCw className={cn("size-4", buscando && "animate-spin")} /> {buscando ? t("Buscando…", "Scanning…") : t("Buscar", "Scan")}
        </Btn>
      </PageHeader>

      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardTitle hint={buscando ? t("buscando…", "scanning…") : t(`${redes.length} redes`, `${redes.length} networks`)}>
            {t("Redes disponíveis", "Available networks")}
          </CardTitle>
          {!buscando && redes.length === 0 && (
            <p className="py-3 text-sm text-muted-foreground">
              {aviso || t("Nenhuma rede encontrada. Toque em Buscar.", "No networks found. Tap Scan.")}
            </p>
          )}
          <div className="-mx-1 divide-y divide-border">
            {redes.map((r) => (
              <button
                key={r.ssid}
                onClick={() => setSel(r)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-lg px-2.5 py-3 text-left transition-colors hover:bg-muted",
                  sel?.ssid === r.ssid && "bg-muted",
                )}
              >
                <IconeSinal s={r.sinal} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{r.ssid}</span>
                  <span className="text-xs text-muted-foreground">{t(`${r.sinal}% de sinal`, `${r.sinal}% signal`)}</span>
                </span>
                {r.seguranca !== "Aberta" ? (
                  <Lock className="size-3.5 text-muted-foreground" />
                ) : (
                  <Pill tone="warn">{t("Aberta", "Open")}</Pill>
                )}
              </button>
            ))}
          </div>
        </Card>

        <Card className="h-fit lg:col-span-2">
          <CardTitle>{sel ? t(`Conectar a "${sel.ssid}"`, `Connect to "${sel.ssid}"`) : t("Selecione uma rede", "Select a network")}</CardTitle>
          {sel ? (
            <div className="space-y-4">
              {sel.seguranca !== "Aberta" ? (
                <Field label={t("Senha da rede", "Network password")}>
                  <Input type="password" value={senha} onChange={(e) => setSenha(e.target.value)} autoFocus />
                </Field>
              ) : null}
              <Notice>
                {t("Ao trocar para o Wi-Fi, o endereço do painel pode mudar. Você terá 3 minutos para confirmar antes que a configuração seja desfeita.",
                   "When switching to Wi-Fi, the panel's address may change. You'll have 3 minutes to confirm before the setting is rolled back.")}
              </Notice>
              <Btn variant="primary" onClick={conectar} className="w-full">
                {t("Conectar", "Connect")}
              </Btn>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t("Escolha uma rede na lista ao lado para conectar.", "Pick a network from the list to connect.")}</p>
          )}
        </Card>
      </div>
    </div>
  )
}
