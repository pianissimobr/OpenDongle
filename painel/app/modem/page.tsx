"use client"

import { useState } from "react"
import { Signal } from "lucide-react"
import { PageHeader, Card, CardTitle, Row, RowGroup, Field, Input, Btn, Pill, Msg, MiniBar } from "@/components/panel/ui"
import { usePanel } from "@/lib/panel/store"
import { t } from "@/lib/panel/i18n"

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
        <PageHeader icon={Signal} title={t("Modem 4G", "4G modem")} />
        <Card className="text-center text-sm text-muted-foreground">{t("Nenhum modem 4G foi detectado neste dongle.", "No 4G modem was detected on this dongle.")}</Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader icon={Signal} title={t("Modem 4G", "4G modem")} desc={t("Conexão de dados móveis via chip SIM.", "Mobile data connection through the SIM card.")}>
        <Pill tone={m.registrado ? "ok" : "warn"}>{m.registrado ? t("Registrado", "Registered") : t("Sem registro", "Not registered")}</Pill>
      </PageHeader>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardTitle>{t("Status da conexão", "Connection status")}</CardTitle>
          <div className="mb-5 rounded-lg border border-border bg-background p-4">
            <div className="mb-2 flex items-baseline justify-between">
              <span className="text-sm text-muted-foreground">{t("Qualidade do sinal", "Signal quality")}</span>
              <span className="text-sm font-medium tabular-nums">
                {m.rssiDbm} dBm · {q.pct}%
              </span>
            </div>
            <MiniBar value={q.pct} tone={q.tone} />
          </div>
          <RowGroup cols={2}>
            <Row title={t("Operadora", "Carrier")} sub={m.operadora} />
            <Row title={t("Chip SIM", "SIM card")} sub={m.simPresente ? t("Presente", "Present") : t("Ausente", "Absent")} />
            <Row title={t("Modo", "Mode")} sub={m.modoOperacao} />
            <Row title="IMEI" sub={m.imei} />
          </RowGroup>
        </Card>

        <Card className="h-fit">
          <CardTitle>APN</CardTitle>
          <div className="space-y-4">
            <Field label={t("Nome do ponto de acesso", "Access point name")} hint={t("Fornecido pela operadora.", "Provided by your carrier.")}>
              <Input value={apn} onChange={(e) => setApn(e.target.value)} />
            </Field>
            <Btn variant="primary" className="w-full" disabled={!apn} onClick={async () => { await processar({ mensagem: t("Salvando o APN", "Saving the APN"), duracao: 6000, acao: "modem-apn", args: { apn } }); setMsg(t("APN salvo. Toque em Reconectar 4G para aplicar agora.", "APN saved. Tap Reconnect 4G to apply it now.")) }}>
              {t("Salvar APN", "Save APN")}
            </Btn>
            <Btn variant="secondary" className="w-full" onClick={() => processar({ mensagem: t("Reconectando o 4G", "Reconnecting 4G"), duracao: 15000, acao: "modem-reconectar" })}>
              {t("Reconectar 4G", "Reconnect 4G")}
            </Btn>
            {msg ? <Msg>{msg}</Msg> : null}
          </div>
        </Card>
      </div>
    </div>
  )
}
