"use client"

import { Wifi, Radio } from "lucide-react"
import { PageHeader, Card, CardTitle, Row, RowGroup, Btn, Pill } from "@/components/panel/ui"
import { usePanel } from "@/lib/panel/store"

export default function WifiConectadoPage() {
  const { estado, processar } = usePanel()
  const end = estado.endereco

  const voltarHotspot = async () => {
    await processar({
      mensagem: "Voltando para o modo hotspot",
      detalhe: "O dongle vai criar a própria rede novamente.",
      duracao: 1500,
      setEstado: "normal",
      ir: "/internet",
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader icon={Wifi} title="Rede Wi-Fi conectada" desc="O dongle está usando uma rede existente para acessar a internet.">
        <Pill tone={estado.internet ? "ok" : "warn"}>{estado.internet ? "Com internet" : "Sem internet"}</Pill>
      </PageHeader>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardTitle>Conexão atual</CardTitle>
          <RowGroup cols={2}>
            <Row title="Rede (SSID)" sub={end?.ssid ?? "—"} />
            <Row title="Endereço IP" sub={end?.ip ?? "—"} />
            <Row title="Segurança" sub="WPA2" />
            <Row title="Status" sub={estado.internet ? "Ativa e com internet" : "Ativa, sem internet"} />
          </RowGroup>
        </Card>

        <Card className="h-fit">
          <CardTitle>Ações</CardTitle>
          <div className="space-y-3">
            <Btn variant="secondary" className="w-full justify-start" onClick={() => processar({ mensagem: "Buscando redes", duracao: 900, ir: "/wifi" })}>
              <Wifi className="size-4" /> Trocar de rede
            </Btn>
            <Btn variant="secondary" className="w-full justify-start" onClick={voltarHotspot}>
              <Radio className="size-4" /> Voltar ao hotspot
            </Btn>
          </div>
        </Card>
      </div>
    </div>
  )
}
