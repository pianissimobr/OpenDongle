"use client"

import { useState } from "react"
import { Radio, Eye, EyeOff } from "lucide-react"
import { PageHeader, Card, CardTitle, Field, Input, Select, Toggle, Btn, Msg, Notice } from "@/components/panel/ui"
import { usePanel } from "@/lib/panel/store"
import { t } from "@/lib/panel/i18n"

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
      mensagem: t("Aplicando configuração do hotspot", "Applying hotspot settings"),
      detalhe: t("A rede Wi-Fi vai reiniciar por alguns segundos.", "The Wi-Fi network will restart for a few seconds."),
      duracao: 8000,
      acao: "set-hotspot",
      args: { ssid, senha },
    })
    setMsg(t("Hotspot atualizado. Reconecte seus aparelhos à rede.", "Hotspot updated. Reconnect your devices to the network."))
  }

  return (
    <div className="space-y-6">
      <PageHeader icon={Radio} title={t("Hotspot Wi-Fi", "Wi-Fi hotspot")} desc={t("A rede que o dongle cria para seus aparelhos se conectarem.", "The network the dongle creates for your devices to connect to.")} />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardTitle>{t("Rede do hotspot", "Hotspot network")}</CardTitle>
          <div className="space-y-4">
            <Field label={t("Nome da rede (SSID)", "Network name (SSID)")}>
              <Input value={ssid} onChange={(e) => setSsid(e.target.value)} maxLength={32} />
            </Field>
            <Field label={t("Senha", "Password")} hint={t("Mínimo de 8 caracteres.", "At least 8 characters.")}>
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
                  aria-label={t(verSenha ? "Ocultar senha" : "Mostrar senha", verSenha ? "Hide password" : "Show password")}
                >
                  {verSenha ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
            </Field>
            <Field label={t("Banda", "Band")}>
              <Select value={banda} onChange={(e) => setBanda(e.target.value)}>
                <option value="5">{t("5 GHz (mais rápido)", "5 GHz (faster)")}</option>
                <option value="2.4">{t("2.4 GHz (mais alcance)", "2.4 GHz (longer range)")}</option>
              </Select>
            </Field>
            <div className="border-t border-border pt-1">
              <Toggle checked={oculta} onChange={setOculta} label={t("Ocultar o nome da rede", "Hide the network name")} />
            </div>
            <div className="flex items-center gap-3 pt-1">
              <Btn variant="primary" onClick={salvar}>
                {t("Salvar alterações", "Save changes")}
              </Btn>
              {msg ? <Msg>{msg}</Msg> : null}
            </div>
          </div>
        </Card>

        <Card className="h-fit">
          <CardTitle>{t("Dica", "Tip")}</CardTitle>
          <Notice tone="info">
            {t("Ao salvar, o Wi-Fi reinicia e os aparelhos conectados caem por alguns segundos. Se você acessa este painel pelo hotspot, reconecte com a nova senha depois.",
               "When you save, the Wi-Fi restarts and connected devices drop for a few seconds. If you access this panel through the hotspot, reconnect with the new password afterward.")}
          </Notice>
        </Card>
      </div>
    </div>
  )
}
