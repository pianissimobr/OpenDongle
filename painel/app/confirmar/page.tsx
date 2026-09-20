"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { ShieldCheck, RotateCcw } from "lucide-react"
import { PageHeader, Card, Btn, Notice } from "@/components/panel/ui"
import { usePanel } from "@/lib/panel/store"
import { t } from "@/lib/panel/i18n"

export default function ConfirmarPage() {
  const router = useRouter()
  const { estado, processar, setEstado } = usePanel()
  const [restante, setRestante] = useState(180)

  useEffect(() => {
    if (!estado.redePendente) return
    const id = setInterval(() => setRestante((r) => Math.max(0, r - 1)), 1000)
    return () => clearInterval(id)
  }, [estado.redePendente])

  const min = String(Math.floor(restante / 60)).padStart(2, "0")
  const seg = String(restante % 60).padStart(2, "0")

  if (!estado.redePendente) {
    return (
      <div className="space-y-6">
        <PageHeader icon={ShieldCheck} title={t("Confirmar mudança de rede", "Confirm network change")} />
        <Card className="text-center">
          <p className="text-sm text-muted-foreground">{t("Não há nenhuma mudança de rede pendente no momento.", "There is no pending network change right now.")}</p>
          <Btn variant="primary" className="mx-auto mt-4" onClick={() => router.push("/internet")}>
            {t("Ir para Internet", "Go to Internet")}
          </Btn>
        </Card>
      </div>
    )
  }

  const manter = async () => {
    await processar({
      mensagem: t("Confirmando a nova configuração de rede", "Confirming the new network settings"),
      duracao: 1200,
      acao: "rede-confirmar",
      ir: "/internet",
    })
  }

  const desfazer = async () => {
    await processar({
      mensagem: t("Revertendo para a configuração anterior", "Rolling back to the previous settings"),
      duracao: 1200,
      acao: "rede-reverter",
      ir: "/internet",
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader
        icon={ShieldCheck}
        title={t("Confirmar mudança de rede", "Confirm network change")}
        desc={t("Você conseguiu abrir o painel no endereço novo — então a conexão está funcionando.", "You managed to open the panel at the new address — so the connection works.")}
      />

      <Card className="flex flex-col items-center gap-5 py-8 text-center">
        <div className="text-5xl font-semibold tabular-nums tracking-tight">
          {min}:{seg}
        </div>
        <p className="max-w-md text-sm text-muted-foreground">
          {t("Se você não confirmar dentro do tempo, o dongle volta sozinho para a configuração anterior. Assim você nunca fica sem acesso.",
             "If you don't confirm in time, the dongle rolls back to the previous settings on its own. That way you're never locked out.")}
        </p>
        <div className="flex flex-wrap justify-center gap-3">
          <Btn variant="primary" onClick={manter}>
            <ShieldCheck className="size-4" /> {t("Manter esta configuração", "Keep these settings")}
          </Btn>
          <Btn variant="secondary" onClick={desfazer}>
            <RotateCcw className="size-4" /> {t("Desfazer agora", "Undo now")}
          </Btn>
        </div>
        {restante === 0 ? <Notice>{t("O tempo acabou. A configuração anterior será restaurada.", "Time is up. The previous settings will be restored.")}</Notice> : null}
      </Card>
    </div>
  )
}
