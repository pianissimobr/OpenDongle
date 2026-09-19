"use client"

import { useState } from "react"
import { Signal } from "lucide-react"
import { PageHeader, Card, CardTitle, Row, RowGroup, Field, Input, Btn, Pill, Msg, MiniBar } from "@/components/panel/ui"
import { usePanel } from "@/lib/panel/store"

function qualidade(dbm: number) {
  const pct = Math.max(0, Math.min(100, ((dbm + 110) / 60) * 100))
  const tone = pct > 60 ? "ok" : pct > 35 ? "warn" : "err"
  return { pct: Math.round(pct), tone: tone as "ok" | "warn" | "err" }
}

export default function ModemPage() {
  const { dados, processar } = usePanel()
  const m = dados.modem
  const [apn, setApn] = useState("")
  const [msg, setMsg] = useState<string | null>(null)
  const q = qualidade(m.rssiDbm)

  if (!m.presente) {
    return (
      <div className="space-y-6">
        <PageHeader icon={Signal} title="Modem 4G" />
        <Card className="text-center text-sm text-muted-foreground">Nenhum modem 4G foi detectado neste dongle.</Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader icon={Signal} title="Modem 4G" desc="Conexão de dados móveis via chip SIM.">
        <Pill tone={m.registrado ? "ok" : "warn"}>{m.registrado ? "Registrado" : "Sem registro"}</Pill>
      </PageHeader>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardTitle>Status da conexão</CardTitle>
          <div className="mb-5 rounded-lg border border-border bg-background p-4">
            <div className="mb-2 flex items-baseline justify-between">
              <span className="text-sm text-muted-foreground">Qualidade do sinal</span>
              <span className="text-sm font-medium tabular-nums">
                {m.rssiDbm} dBm · {q.pct}%
              </span>
            </div>
            <MiniBar value={q.pct} tone={q.tone} />
          </div>
          <RowGroup cols={2}>
            <Row title="Operadora" sub={m.operadora} />
            <Row title="Chip SIM" sub={m.simPresente ? "Presente" : "Ausente"} />
            <Row title="Modo" sub={m.modoOperacao} />
            <Row title="IMEI" sub={m.imei} />
          </RowGroup>
        </Card>

        <Card className="h-fit">
          <CardTitle>APN</CardTitle>
          <div className="space-y-4">
            <Field label="Nome do ponto de acesso" hint="Fornecido pela operadora.">
              <Input value={apn} onChange={(e) => setApn(e.target.value)} />
            </Field>
            <Btn variant="primary" className="w-full" disabled={!apn} onClick={async () => { await processar({ mensagem: "Salvando o APN", duracao: 6000, acao: "modem-apn", args: { apn } }); setMsg("APN salvo. Toque em Reconectar 4G para aplicar agora.") }}>
              Salvar APN
            </Btn>
            <Btn variant="secondary" className="w-full" onClick={() => processar({ mensagem: "Reconectando o 4G", duracao: 15000, acao: "modem-reconectar" })}>
              Reconectar 4G
            </Btn>
            {msg ? <Msg>{msg}</Msg> : null}
          </div>
        </Card>
      </div>
    </div>
  )
}
