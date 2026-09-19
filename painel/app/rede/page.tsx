"use client"

import { useState } from "react"
import { Network, Pin, PinOff } from "lucide-react"
import { PageHeader, Card, CardTitle, Field, Input, Btn, Pill, Msg, Row, RowGroup } from "@/components/panel/ui"
import { usePanel } from "@/lib/panel/store"

export default function RedePage() {
  const { dados, setDados, processar } = usePanel()
  const lan = dados.lan
  const [ip, setIp] = useState(lan.ip)
  const [ini, setIni] = useState(String(lan.dhcpInicio))
  const [fim, setFim] = useState(String(lan.dhcpFim))
  const [msg, setMsg] = useState<string | null>(null)

  const salvar = async () => {
    await processar({
      mensagem: "Aplicando configuração da LAN",
      detalhe: "Mudar o IP do dongle pode derrubar o acesso; confirme depois.",
      duracao: 6000,
      acao: "lan-set",
      args: { ip, inicio: Number(ini), fim: Number(fim), prefixo: lan.prefixo, lease: lan.lease },
    })
    setMsg("Configuração da rede local salva.")
  }

  const alternarFixo = async (mac: string) => {
    const c = dados.lan.clientes.find((x) => x.mac === mac)
    if (!c) return
    await processar({
      mensagem: c.fixo ? "Removendo IP fixo" : "Fixando IP do aparelho",
      duracao: 3000,
      acao: c.fixo ? "fixo-rm" : "fixo-add",
      args: c.fixo ? { mac } : { mac, ip: c.ip, nome: c.nome || "aparelho" },
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader icon={Network} title="LAN, DHCP e IP fixo" desc="Rede local que o dongle entrega aos aparelhos conectados." />

      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-2 h-fit">
          <CardTitle>Configuração</CardTitle>
          <div className="space-y-4">
            <Field label="Endereço IP do dongle">
              <Input value={ip} onChange={(e) => setIp(e.target.value)} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Início do DHCP">
                <Input value={ini} onChange={(e) => setIni(e.target.value)} />
              </Field>
              <Field label="Fim do DHCP">
                <Input value={fim} onChange={(e) => setFim(e.target.value)} />
              </Field>
            </div>
            <Field label="Tempo de concessão">
              <Input value={lan.lease} readOnly />
            </Field>
            <Btn variant="primary" className="w-full" onClick={salvar}>
              Salvar configuração
            </Btn>
            {msg ? <Msg>{msg}</Msg> : null}
          </div>
        </Card>

        <Card className="lg:col-span-3">
          <CardTitle hint={`${lan.clientes.length} conectados`}>Aparelhos na rede</CardTitle>
          <div className="-mx-1 divide-y divide-border">
            {lan.clientes.map((c) => (
              <Row
                key={c.mac}
                title={c.nome}
                sub={`${c.ip} · ${c.mac}`}
                action={
                  <>
                    {c.fixo ? <Pill tone="brand">IP fixo</Pill> : null}
                    <Btn size="sm" variant="ghost" onClick={() => alternarFixo(c.mac)}>
                      {c.fixo ? <PinOff className="size-4" /> : <Pin className="size-4" />}
                      {c.fixo ? "Soltar" : "Fixar"}
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
