"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { ArrowRight, Wifi, Radio, Gauge, Thermometer, HardDrive, Info, TriangleAlert, CircleCheck } from "lucide-react"
import { CATEGORIAS, CAT_AJUDA } from "@/lib/panel/nav"
import { CatIcon } from "@/components/panel/icon"
import { Card, Pill, Stat } from "@/components/panel/ui"
import { saudacao, usePanel, type Severity } from "@/lib/panel/store"
import { t } from "@/lib/panel/i18n"
import { cn } from "@/lib/utils"

const DESC: Record<string, [string, string]> = {
  internet: ["Hotspot, Wi-Fi, modem 4G, portas e acesso remoto.", "Hotspot, Wi-Fi, 4G modem, ports and remote access."],
  perfil: ["Sua conta, senha e foto de administrador.", "Your account, password and admin photo."],
  dispositivos: ["Bluetooth, USB, áudio e luzes do aparelho.", "Bluetooth, USB, audio and the device's lights."],
  sistema: ["Atualizações, hora, espaço, hardware e backup.", "Updates, time, space, hardware and backup."],
}

const SEV: Record<Severity, { color: string; Icon: typeof Info; tone: string }> = {
  info: { color: "text-brand", Icon: Info, tone: "border-brand/30 bg-brand/5" },
  success: { color: "text-ok", Icon: CircleCheck, tone: "border-ok/30 bg-ok-soft/40" },
  warning: { color: "text-warn", Icon: TriangleAlert, tone: "border-warn/40 bg-warn-soft/40" },
  error: { color: "text-err", Icon: TriangleAlert, tone: "border-err/40 bg-err-soft/40" },
}

export default function HomePage() {
  const { estado, saude, dados } = usePanel()
  // A saudação depende da hora e do nome: calculada só no navegador. Na
  // renderização valeria a hora do build no HTML pré-gerado ("Boa noite" se
  // compilado à noite) e a hora atual no cliente — texto diferente, erro #418.
  const [ola, setOla] = useState("")
  useEffect(() => { setOla(saudacao()) }, [estado, dados])
  const rec = estado.recomendacao
  const online = estado.internet
  const ModoIcon = estado.modo === "wifi" ? Wifi : Radio

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="min-h-8 text-2xl font-semibold tracking-tight">{ola}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t("Aqui está um resumo do seu dongle.", "Here's a summary of your dongle.")}</p>
        </div>
        <Pill tone={online ? "ok" : "warn"}>
          <ModoIcon className="size-3.5" />
          {estado.modo === "wifi"
            ? t(`Conectado a ${estado.endereco?.ssid ?? "Wi-Fi"}`, `Connected to ${estado.endereco?.ssid ?? "Wi-Fi"}`)
            : `Hotspot ${estado.ssidHotspot ?? ""}`}
          {online ? t(" · online", " · online") : t(" · sem internet", " · no internet")}
        </Pill>
      </div>

      {rec ? (
        <div className={cn("flex flex-col gap-4 rounded-xl border p-5 sm:flex-row sm:items-center", SEV[rec.severity].tone)}>
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-background">
            {(() => {
              const I = SEV[rec.severity].Icon
              return <I className={cn("size-5", SEV[rec.severity].color)} />
            })()}
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="font-semibold">{rec.title}</h2>
            <p className="mt-0.5 text-sm text-muted-foreground">{rec.description}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {rec.secondary.map((s) => (
              <Link
                key={s.route}
                href={s.route}
                className="inline-flex h-8 items-center rounded-lg px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted"
              >
                {s.label}
              </Link>
            ))}
            <Link
              href={rec.primary.route}
              className="inline-flex h-8 items-center gap-2 rounded-lg bg-primary px-3 text-xs font-medium text-primary-foreground hover:bg-primary/90"
            >
              {rec.primary.label}
              <ArrowRight className="size-3.5" />
            </Link>
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Link href="/status" className="block transition-transform hover:-translate-y-0.5">
          <Stat
            label={
              <span className="flex items-center gap-1.5">
                <Gauge className="size-3.5" /> {t("Memória RAM", "RAM memory")}
              </span>
            }
            value={saude ? `${saude.ramPct}%` : "—"}
            tone={!saude ? "" : saude.ramPct > 85 ? "err" : saude.ramPct > 70 ? "warn" : ""}
            bar={saude?.ramPct ?? 0}
          />
        </Link>
        <Link href="/status" className="block transition-transform hover:-translate-y-0.5">
          <Stat
            label={
              <span className="flex items-center gap-1.5">
                <Thermometer className="size-3.5" /> {t("Temperatura", "Temperature")}
              </span>
            }
            value={saude ? `${saude.tempC}°` : "—"}
            tone={!saude ? "" : saude.tempC > 70 ? "err" : saude.tempC > 60 ? "warn" : ""}
            bar={saude ? (saude.tempC / 90) * 100 : 0}
          />
        </Link>
        <Link href="/espaco" className="block transition-transform hover:-translate-y-0.5">
          <Stat
            label={
              <span className="flex items-center gap-1.5">
                <HardDrive className="size-3.5" /> {t("Disco", "Disk")}
              </span>
            }
            value={saude ? `${saude.discoPct}%` : "—"}
            bar={saude?.discoPct ?? 0}
          />
        </Link>
        <Link href="/internet" className="block transition-transform hover:-translate-y-0.5">
          <Stat
            label={
              <span className="flex items-center gap-1.5">
                <ModoIcon className="size-3.5" /> {t("Conexão", "Connection")}
              </span>
            }
            value={online ? "OK" : "—"}
            tone={online ? "" : "warn"}
          />
        </Link>
      </div>

      <div>
        <h2 className="mb-3 text-sm font-semibold text-muted-foreground">{t("Configurações", "Settings")}</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {CATEGORIAS.filter((c) => c.id !== "inicio").map((c) => (
            <Link key={c.id} href={c.rota} className="group">
              <Card className="flex h-full items-center gap-4 transition-colors group-hover:border-foreground/20 group-hover:bg-muted/40">
                <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-muted text-foreground">
                  <CatIcon name={c.icon} className="size-5" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block font-medium">{t(c.nome, c.nomeEn)}</span>
                  <span className="mt-0.5 block text-sm text-muted-foreground">{t(...(DESC[c.id] as [string, string]))}</span>
                </span>
                <ArrowRight className="size-4 shrink-0 text-muted-foreground/50 transition-transform group-hover:translate-x-0.5" />
              </Card>
            </Link>
          ))}
          <Link href={CAT_AJUDA.rota} className="group">
            <Card className="flex h-full items-center gap-4 transition-colors group-hover:border-foreground/20 group-hover:bg-muted/40">
              <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-muted text-foreground">
                <CatIcon name={CAT_AJUDA.icon} className="size-5" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-medium">{t("Ajuda e recuperação", "Help and recovery")}</span>
                <span className="mt-0.5 block text-sm text-muted-foreground">
                  {t("Perdi o acesso, como recuperar e dúvidas comuns.", "Lost access, how to recover, and common questions.")}
                </span>
              </span>
              <ArrowRight className="size-4 shrink-0 text-muted-foreground/50 transition-transform group-hover:translate-x-0.5" />
            </Card>
          </Link>
        </div>
      </div>
    </div>
  )
}
