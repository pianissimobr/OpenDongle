"use client"

import { Globe, Wifi, Radio, Signal, Network, Shield, MonitorSmartphone, VenetianMask } from "lucide-react"
import { PageHeader, Card, Row, RowGroup, Pill } from "@/components/panel/ui"
import { usePanel } from "@/lib/panel/store"

export default function InternetPage() {
  const { estado, dados, avancadas } = usePanel()
  const online = estado.internet

  return (
    <div className="space-y-6">
      <PageHeader
        icon={Globe}
        title="Internet e rede"
        desc="Escolha como o dongle acessa a internet e como os aparelhos se conectam a ele."
      >
        <Pill tone={online ? "ok" : "warn"}>{online ? "Com internet" : "Sem internet"}</Pill>
      </PageHeader>

      <Card>
        <RowGroup cols={2}>
          <Row
            icon={Radio}
            title="Hotspot Wi-Fi"
            sub={estado.ssidHotspot ? `Rede "${estado.ssidHotspot}"` : "Desligado"}
            href="/hotspot"
          />
          <Row
            icon={Wifi}
            title="Conectar a uma rede"
            sub={estado.endereco ? `Conectado a "${estado.endereco.ssid}"` : "Usar Wi-Fi de casa"}
            href={estado.modo === "wifi" ? "/wifi-conectado" : "/wifi"}
          />
          <Row
            icon={Signal}
            title="Modem 4G"
            sub={dados.modem.presente ? `${dados.modem.operadora} · ${dados.modem.rssiDbm} dBm` : "Não detectado"}
            href="/modem"
          />
          <Row
            icon={Network}
            title="LAN, DHCP e IP fixo"
            sub={`${dados.lan.ip}/${dados.lan.prefixo} · ${dados.lan.clientes.length} aparelhos`}
            href="/rede"
          />
          <Row
            icon={Shield}
            title="Firewall e portas"
            sub={`${dados.firewall.redirecionamentos.length} redirecionamentos`}
            href="/firewall"
          />
          <Row icon={MonitorSmartphone} title="Acesso remoto" sub="Acessar o dongle de longe" href="/remoto" />
          {avancadas ? (
            <Row icon={VenetianMask} title="Navegação via Tor" sub="Rotear a saída pela rede Tor" href="/tor" />
          ) : null}
        </RowGroup>
      </Card>
    </div>
  )
}
