"use client"

import { useState } from "react"
import { CircleDot, KeyRound } from "lucide-react"
import { Card, Field, Input, Btn, Notice } from "@/components/panel/ui"
import { t } from "@/lib/panel/i18n"
import { LangCorner } from "@/components/panel/lang-corner"

export default function LoginPage() {
  const [senha, setSenha] = useState("")
  const [erro, setErro] = useState("")
  const [enviando, setEnviando] = useState(false)

  // volta pra rota que pediu login (o backend manda ?v=/algo no redirect)
  const voltar = (() => {
    if (typeof window === "undefined") return "/"
    const v = new URLSearchParams(window.location.search).get("v") || "/"
    return v.startsWith("/") && !v.startsWith("//") ? v : "/"
  })()

  async function entrar(e: React.FormEvent) {
    e.preventDefault()
    setErro("")
    setEnviando(true)
    try {
      const r = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ senha, voltar }),
      })
      const d = await r.json().catch(() => ({}))
      if (r.ok && d.ok) {
        window.location.href = d.voltar || voltar
      } else {
        setErro(d.erro || t("Senha incorreta.", "Incorrect password."))
        setEnviando(false)
      }
    } catch {
      setErro(t("Não foi possível falar com o dongle.", "Could not reach the dongle."))
      setEnviando(false)
    }
  }

  return (
    <div className="relative flex min-h-svh items-center justify-center bg-background px-4">
      <LangCorner />
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center gap-2.5 text-center">
          <span className="flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <CircleDot className="size-6" />
          </span>
          <h1 className="text-lg font-semibold tracking-tight">OpenDongle</h1>
          <p className="text-sm text-muted-foreground">{t("Entre com a senha de administração para continuar.", "Sign in with the admin password to continue.")}</p>
        </div>
        <Card>
          <form onSubmit={entrar} className="space-y-4">
            <Field label={t("Senha de administração", "Admin password")}>
              <Input
                type="password"
                autoFocus
                autoComplete="current-password"
                value={senha}
                onChange={(e) => setSenha(e.target.value)}
                placeholder={t("Sua senha", "Your password")}
              />
            </Field>
            {erro ? <Notice tone="warn">{erro}</Notice> : null}
            <Btn type="submit" variant="primary" className="w-full" disabled={enviando || !senha}>
              <KeyRound className="size-4" />
              {enviando ? t("Entrando…", "Signing in…") : t("Entrar", "Sign in")}
            </Btn>
          </form>
        </Card>
        <p className="mt-4 text-center text-xs text-muted-foreground">
          {t("Esqueceu a senha? Recupere pelo cabo USB ou pelo acesso root.",
             "Forgot the password? Recover it via the USB cable or root access.")}
        </p>
      </div>
    </div>
  )
}
