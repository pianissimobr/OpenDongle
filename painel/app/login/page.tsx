"use client"

import { useState } from "react"
import { CircleDot, KeyRound } from "lucide-react"
import { Card, Field, Input, Btn, Notice } from "@/components/panel/ui"

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
        setErro(d.erro || "Senha incorreta.")
        setEnviando(false)
      }
    } catch {
      setErro("Não foi possível falar com o dongle.")
      setEnviando(false)
    }
  }

  return (
    <div className="flex min-h-svh items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center gap-2.5 text-center">
          <span className="flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <CircleDot className="size-6" />
          </span>
          <h1 className="text-lg font-semibold tracking-tight">OpenDongle</h1>
          <p className="text-sm text-muted-foreground">Entre com a senha de administração para continuar.</p>
        </div>
        <Card>
          <form onSubmit={entrar} className="space-y-4">
            <Field label="Senha de administração">
              <Input
                type="password"
                autoFocus
                autoComplete="current-password"
                value={senha}
                onChange={(e) => setSenha(e.target.value)}
                placeholder="Sua senha"
              />
            </Field>
            {erro ? <Notice tone="warn">{erro}</Notice> : null}
            <Btn type="submit" variant="primary" className="w-full" disabled={enviando || !senha}>
              <KeyRound className="size-4" />
              {enviando ? "Entrando…" : "Entrar"}
            </Btn>
          </form>
        </Card>
        <p className="mt-4 text-center text-xs text-muted-foreground">
          Esqueceu a senha? Recupere pelo cabo USB ou pelo acesso root.
        </p>
      </div>
    </div>
  )
}
