"use client"

import { Wifi, Radio } from "lucide-react"
import { PageHeader, Card, CardTitle, Row, RowGroup, Btn, Pill } from "@/components/panel/ui"
import { usePanel } from "@/lib/panel/store"
import { t } from "@/lib/panel/i18n"

export default function WifiConectadoPage() {
  const { estado, processar } = usePanel()
  const end = estado.endereco

  const voltarHotspot = async () => {
    await processar({
      mensagem: t("Voltando para o modo hotspot", "Switching back to hotspot mode"),
      detalhe: t("O dongle vai criar a própria rede novamente.", "The dongle will create its own network again."),
      duracao: 8000,
      acao: "mode-hotspot",
      ir: "/internet",
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader
        icon={Wifi}
        title={t("Rede Wi-Fi conectada", "Wi-Fi network connected")}
        desc={t("O dongle está usando uma rede existente para acessar a internet.", "The dongle is using an existing network to reach the internet.")}
      >
        <Pill tone={estado.internet ? "ok" : "warn"}>{estado.internet ? t("Com internet", "Online") : t("Sem internet", "Offline")}</Pill>
      </PageHeader>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardTitle>{t("Conexão atual", "Current connection")}</CardTitle>
          <RowGroup cols={2}>
            <Row title={t("Rede (SSID)", "Network (SSID)")} sub={end?.ssid ?? "—"} />
            <Row title={t("Endereço IP", "IP address")} sub={end?.ip ?? "—"} />
            <Row title={t("Segurança", "Security")} sub="WPA2" />
            <Row title={t("Status", "Status")} sub={estado.internet ? t("Ativa e com internet", "Active, with internet") : t("Ativa, sem internet", "Active, no internet")} />
          </RowGroup>
        </Card>

        <Card className="h-fit">
          <CardTitle>{t("Ações", "Actions")}</CardTitle>
          <div className="space-y-3">
            <Btn variant="secondary" className="w-full justify-start" onClick={() => processar({ mensagem: t("Buscando redes", "Scanning networks"), duracao: 900, ir: "/wifi" })}>
              <Wifi className="size-4" /> {t("Trocar de rede", "Switch network")}
            </Btn>
            <Btn variant="secondary" className="w-full justify-start" onClick={voltarHotspot}>
              <Radio className="size-4" /> {t("Voltar ao hotspot", "Back to hotspot")}
            </Btn>
          </div>
        </Card>
      </div>
    </div>
  )
}
