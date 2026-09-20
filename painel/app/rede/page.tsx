"use client"

import { useState } from "react"
import { Network, Pin, PinOff } from "lucide-react"
import { PageHeader, Card, CardTitle, Field, Input, Btn, Pill, Msg, Row, RowGroup } from "@/components/panel/ui"
import { usePanel } from "@/lib/panel/store"
import { t } from "@/lib/panel/i18n"

export default function RedePage() {
  const { dados, setDados, processar } = usePanel()
  const lan = dados.lan
  const [ip, setIp] = useState(lan.ip)
  const [ini, setIni] = useState(String(lan.dhcpInicio))
  const [fim, setFim] = useState(String(lan.dhcpFim))
  const [msg, setMsg] = useState<string | null>(null)

  const salvar = async () => {
    await processar({
      mensagem: t("Aplicando configuração da LAN", "Applying LAN settings"),
      detalhe: t("Mudar o IP do dongle pode derrubar o acesso; confirme depois.", "Changing the dongle IP may drop your access; confirm afterwards."),
      duracao: 6000,
      acao: "lan-set",
      args: { ip, inicio: Number(ini), fim: Number(fim), prefixo: lan.prefixo, lease: lan.lease },
    })
    setMsg(t("Configuração da rede local salva.", "Local network settings saved."))
  }

  const alternarFixo = async (mac: string) => {
    const c = dados.lan.clientes.find((x) => x.mac === mac)
    if (!c) return
    await processar({
      mensagem: c.fixo ? t("Removendo IP fixo", "Removing static IP") : t("Fixando IP do aparelho", "Pinning the device IP"),
      duracao: 3000,
      acao: c.fixo ? "fixo-rm" : "fixo-add",
      args: c.fixo ? { mac } : { mac, ip: c.ip, nome: c.nome || "aparelho" },
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader icon={Network} title={t("LAN, DHCP e IP fixo", "LAN, DHCP and static IP")} desc={t("Rede local que o dongle entrega aos aparelhos conectados.", "The local network the dongle hands out to connected devices.")} />

      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-2 h-fit">
          <CardTitle>{t("Configuração", "Settings")}</CardTitle>
          <div className="space-y-4">
            <Field label={t("Endereço IP do dongle", "Dongle IP address")}>
              <Input value={ip} onChange={(e) => setIp(e.target.value)} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("Início do DHCP", "DHCP start")}>
                <Input value={ini} onChange={(e) => setIni(e.target.value)} />
              </Field>
              <Field label={t("Fim do DHCP", "DHCP end")}>
                <Input value={fim} onChange={(e) => setFim(e.target.value)} />
              </Field>
            </div>
            <Field label={t("Tempo de concessão", "Lease time")}>
              <Input value={lan.lease} readOnly />
            </Field>
            <Btn variant="primary" className="w-full" onClick={salvar}>
              {t("Salvar configuração", "Save settings")}
            </Btn>
            {msg ? <Msg>{msg}</Msg> : null}
          </div>
        </Card>

        <Card className="lg:col-span-3">
          <CardTitle hint={t(`${lan.clientes.length} conectados`, `${lan.clientes.length} connected`)}>{t("Aparelhos na rede", "Devices on the network")}</CardTitle>
          <div className="-mx-1 divide-y divide-border">
            {lan.clientes.map((c) => (
              <Row
                key={c.mac}
                title={c.nome}
                sub={`${c.ip} · ${c.mac}`}
                action={
                  <>
                    {c.fixo ? <Pill tone="brand">{t("IP fixo", "Static IP")}</Pill> : null}
                    <Btn size="sm" variant="ghost" onClick={() => alternarFixo(c.mac)}>
                      {c.fixo ? <PinOff className="size-4" /> : <Pin className="size-4" />}
                      {c.fixo ? t("Soltar", "Unpin") : t("Fixar", "Pin")}
                    </Btn>
                  </>
                }
              />
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
