"use client"

import { useState } from "react"
import { Radio, Eye, EyeOff } from "lucide-react"
import { PageHeader, Card, CardTitle, Field, Input, Select, Toggle, Btn, Msg, Notice } from "@/components/panel/ui"
import { usePanel } from "@/lib/panel/store"

export default function HotspotPage() {
  const { estado, processar } = usePanel()
  const [ssid, setSsid] = useState(estado.ssidHotspot ?? "OpenDongle")
  const [senha, setSenha] = useState("dongle123")
  const [banda, setBanda] = useState("5")
  const [oculta, setOculta] = useState(false)
  const [verSenha, setVerSenha] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  const salvar = async () => {
    setMsg(null)
    await processar({
      mensagem: "Aplicando configuração do hotspot",
      detalhe: "A rede Wi-Fi vai reiniciar por alguns segundos.",
      duracao: 8000,
      acao: "set-hotspot",
      args: { ssid, senha },
    })
    setMsg("Hotspot atualizado. Reconecte seus aparelhos à rede.")
  }

  return (
    <div className="space-y-6">
      <PageHeader icon={Radio} title="Hotspot Wi-Fi" desc="A rede que o dongle cria para seus aparelhos se conectarem." />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardTitle>Rede do hotspot</CardTitle>
          <div className="space-y-4">
            <Field label="Nome da rede (SSID)">
              <Input value={ssid} onChange={(e) => setSsid(e.target.value)} maxLength={32} />
            </Field>
            <Field label="Senha" hint="Mínimo de 8 caracteres.">
              <div className="relative">
                <Input
                  type={verSenha ? "text" : "password"}
                  value={senha}
                  onChange={(e) => setSenha(e.target.value)}
                  className="pr-10"
                />
                <button
                  type="button"
                  onClick={() => setVerSenha((v) => !v)}
                  className="absolute right-2 top-1/2 flex size-7 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
                  aria-label={verSenha ? "Ocultar senha" : "Mostrar senha"}
                >
                  {verSenha ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
            </Field>
            <Field label="Banda">
              <Select value={banda} onChange={(e) => setBanda(e.target.value)}>
                <option value="5">5 GHz (mais rápido)</option>
                <option value="2.4">2.4 GHz (mais alcance)</option>
              </Select>
            </Field>
            <div className="border-t border-border pt-1">
              <Toggle checked={oculta} onChange={setOculta} label="Ocultar o nome da rede" />
            </div>
            <div className="flex items-center gap-3 pt-1">
              <Btn variant="primary" onClick={salvar}>
                Salvar alterações
              </Btn>
              {msg ? <Msg>{msg}</Msg> : null}
            </div>
          </div>
        </Card>

        <Card className="h-fit">
          <CardTitle>Dica</CardTitle>
          <Notice tone="info">
            Ao salvar, o Wi-Fi reinicia e os aparelhos conectados caem por alguns segundos. Se você acessa este painel
            pelo hotspot, reconecte com a nova senha depois.
          </Notice>
        </Card>
      </div>
    </div>
  )
}
