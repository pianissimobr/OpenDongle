"use client"

import { useState, useEffect } from "react"
import { Wifi, SignalHigh, SignalMedium, SignalLow, Lock, RefreshCw } from "lucide-react"
import { PageHeader, Card, CardTitle, Field, Input, Btn, Notice, Pill } from "@/components/panel/ui"
import { usePanel } from "@/lib/panel/store"
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
    } catch { setAviso("Não foi possível buscar redes.") }
    setBuscando(false)
  }
  useEffect(() => { buscar() }, [])

  const conectar = async () => {
    if (!sel) return
    await processar({
      mensagem: `Conectando a "${sel.ssid}"`,
      detalhe: "O dongle vai testar a conexão antes de confirmar.",
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
        title="Conectar a uma rede Wi-Fi"
        desc="Use uma rede existente (como o Wi-Fi de casa) para dar internet ao dongle."
      >
        <Btn size="sm" variant="ghost" onClick={buscar} disabled={buscando}>
          <RefreshCw className={cn("size-4", buscando && "animate-spin")} /> {buscando ? "Buscando…" : "Buscar"}
        </Btn>
      </PageHeader>

      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardTitle hint={buscando ? "buscando…" : `${redes.length} redes`}>Redes disponíveis</CardTitle>
          {!buscando && redes.length === 0 && <p className="py-3 text-sm text-muted-foreground">{aviso || "Nenhuma rede encontrada. Toque em Buscar."}</p>}
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
                  <span className="text-xs text-muted-foreground">{r.sinal}% de sinal</span>
                </span>
                {r.seguranca !== "Aberta" ? (
                  <Lock className="size-3.5 text-muted-foreground" />
                ) : (
                  <Pill tone="warn">Aberta</Pill>
                )}
              </button>
            ))}
          </div>
        </Card>

        <Card className="h-fit lg:col-span-2">
          <CardTitle>{sel ? `Conectar a "${sel.ssid}"` : "Selecione uma rede"}</CardTitle>
          {sel ? (
            <div className="space-y-4">
              {sel.seguranca !== "Aberta" ? (
                <Field label="Senha da rede">
                  <Input type="password" value={senha} onChange={(e) => setSenha(e.target.value)} autoFocus />
                </Field>
              ) : null}
              <Notice>
                Ao trocar para o Wi-Fi, o endereço do painel pode mudar. Você terá 3 minutos para confirmar antes que a
                configuração seja desfeita.
              </Notice>
              <Btn variant="primary" onClick={conectar} className="w-full">
                Conectar
              </Btn>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Escolha uma rede na lista ao lado para conectar.</p>
          )}
        </Card>
      </div>
    </div>
  )
}
