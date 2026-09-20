"use client"

import { Globe, Wifi, Radio, Signal, Network, Shield, MonitorSmartphone, VenetianMask } from "lucide-react"
import { PageHeader, Card, Row, RowGroup, Pill } from "@/components/panel/ui"
import { usePanel } from "@/lib/panel/store"
import { t } from "@/lib/panel/i18n"

export default function InternetPage() {
  const { estado, dados, avancadas } = usePanel()
  const online = estado.internet

  return (
    <div className="space-y-6">
      <PageHeader
        icon={Globe}
        title={t("Internet e rede", "Internet and network")}
        desc={t("Escolha como o dongle acessa a internet e como os aparelhos se conectam a ele.",
                "Choose how the dongle reaches the internet and how devices connect to it.")}
      >
        <Pill tone={online ? "ok" : "warn"}>{online ? t("Com internet", "Online") : t("Sem internet", "Offline")}</Pill>
      </PageHeader>

      <Card>
        <RowGroup cols={2}>
          <Row
            icon={Radio}
            title={t("Hotspot Wi-Fi", "Wi-Fi hotspot")}
            sub={estado.ssidHotspot ? t(`Rede "${estado.ssidHotspot}"`, `Network "${estado.ssidHotspot}"`) : t("Desligado", "Off")}
            href="/hotspot"
          />
          <Row
            icon={Wifi}
            title={t("Conectar a uma rede", "Connect to a network")}
            sub={estado.endereco ? t(`Conectado a "${estado.endereco.ssid}"`, `Connected to "${estado.endereco.ssid}"`) : t("Usar Wi-Fi de casa", "Use home Wi-Fi")}
            href={estado.modo === "wifi" ? "/wifi-conectado" : "/wifi"}
          />
          <Row
            icon={Signal}
            title={t("Modem 4G", "4G modem")}
            sub={dados.modem.presente ? `${dados.modem.operadora} · ${dados.modem.rssiDbm} dBm` : t("Não detectado", "Not detected")}
            href="/modem"
          />
          <Row
            icon={Network}
            title={t("LAN, DHCP e IP fixo", "LAN, DHCP and static IP")}
            sub={t(`${dados.lan.ip}/${dados.lan.prefixo} · ${dados.lan.clientes.length} aparelhos`,
                   `${dados.lan.ip}/${dados.lan.prefixo} · ${dados.lan.clientes.length} devices`)}
            href="/rede"
          />
          <Row
            icon={Shield}
            title={t("Firewall e portas", "Firewall and ports")}
            sub={t(`${dados.firewall.redirecionamentos.length} redirecionamentos`, `${dados.firewall.redirecionamentos.length} port forwards`)}
            href="/firewall"
          />
          <Row icon={MonitorSmartphone} title={t("Acesso remoto", "Remote access")} sub={t("Acessar o dongle de longe", "Access the dongle from afar")} href="/remoto" />
          {avancadas ? (
            <Row icon={VenetianMask} title={t("Navegação via Tor", "Browsing via Tor")} sub={t("Rotear a saída pela rede Tor", "Route traffic through the Tor network")} href="/tor" />
          ) : null}
        </RowGroup>
      </Card>
    </div>
  )
}
