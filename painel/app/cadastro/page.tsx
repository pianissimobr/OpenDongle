"use client"

import { useState } from "react"
import { CircleDot, ArrowRight, ArrowLeft, Check, Camera } from "lucide-react"
import { Card, Field, Input, Btn, Notice } from "@/components/panel/ui"
import { fotoParaDataUrl } from "@/lib/panel/foto"

const PASSOS = ["Senha do sistema", "Seu nome", "Seu acesso", "Sua foto"]

export default function CadastroPage() {
  const [passo, setPasso] = useState(1)
  const [senhaRoot, setSenhaRoot] = useState("")
  const [nome, setNome] = useState("")
  const [sobrenome, setSobrenome] = useState("")
  const [usuario, setUsuario] = useState("")
  const [mexeuUsuario, setMexeuUsuario] = useState(false)
  const [senha, setSenha] = useState("")
  const [confirmacao, setConfirmacao] = useState("")
  const [foto, setFoto] = useState("")
  const [erro, setErro] = useState("")
  const [enviando, setEnviando] = useState(false)

  // sugere um usuário a partir do nome, até a pessoa editar à mão
  const sugereUsuario = (n: string) =>
    n.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]/g, "")

  const validaPasso = () => {
    setErro("")
    if (passo === 1) {
      if (senhaRoot.length < 6) return "A senha do sistema precisa de ao menos 6 caracteres."
      if (senhaRoot === "1") return "Escolha uma senha diferente da de fábrica."
    }
    if (passo === 2) {
      if (!nome.trim() || !sobrenome.trim()) return "Informe nome e sobrenome."
    }
    if (passo === 3) {
      if (!/^[a-z][a-z0-9_-]{2,31}$/.test(usuario)) return "Usuário: minúsculas, números, - ou _ (começa por letra)."
      if (senha.length < 6) return "A sua senha precisa de ao menos 6 caracteres."
      if (senha !== confirmacao) return "As duas senhas não são iguais."
      if (senha === senhaRoot) return "Use uma senha diferente da senha do sistema."
    }
    return ""
  }

  const avancar = () => {
    const e = validaPasso()
    if (e) { setErro(e); return }
    if (passo === 1 && !mexeuUsuario) setUsuario(sugereUsuario(nome) || usuario)
    setPasso((p) => p + 1)
  }

  const escolherFoto = async (file?: File) => {
    if (!file) return
    try { setFoto(await fotoParaDataUrl(file)) } catch { setErro("Não consegui ler essa imagem.") }
  }

  const concluir = async () => {
    setErro(""); setEnviando(true)
    try {
      const r = await fetch("/api/cadastro", {
        method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
        body: JSON.stringify({ senhaRoot, nome, sobrenome, usuario, senha, confirmacao, foto }),
      })
      const d = await r.json().catch(() => ({}))
      if (r.ok && d.ok) { window.location.href = "/" }
      else { setErro(d.erro || "Não foi possível concluir o cadastro."); if (d.etapa) setPasso(d.etapa); setEnviando(false) }
    } catch { setErro("Não foi possível falar com o dongle."); setEnviando(false) }
  }

  return (
    <div className="flex min-h-svh items-center justify-center bg-background px-4 py-8">
      <div className="w-full max-w-md">
        <div className="mb-6 flex flex-col items-center gap-2.5 text-center">
          <span className="flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <CircleDot className="size-6" />
          </span>
          <h1 className="text-lg font-semibold tracking-tight">Bem-vindo ao OpenDongle</h1>
          <p className="text-sm text-muted-foreground">Vamos configurar o seu dongle. Leva um minuto.</p>
        </div>

        <div className="mb-4 flex items-center gap-2">
          {PASSOS.map((_, i) => (
            <span key={i} className={`h-1.5 flex-1 rounded-full ${i + 1 <= passo ? "bg-brand" : "bg-muted"}`} />
          ))}
        </div>

        <Card>
          <p className="mb-1 text-xs font-medium text-muted-foreground">Passo {passo} de {PASSOS.length}</p>
          <h2 className="mb-4 text-base font-semibold">{PASSOS[passo - 1]}</h2>

          {passo === 1 && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">A senha de administração do sistema (root). Guarde-a: é a chave de recuperação se você esquecer a sua senha.</p>
              <Field label="Senha do sistema (root)"><Input type="password" value={senhaRoot} onChange={(e) => setSenhaRoot(e.target.value)} autoFocus /></Field>
            </div>
          )}
          {passo === 2 && (
            <div className="space-y-4">
              <Field label="Nome"><Input value={nome} onChange={(e) => setNome(e.target.value)} autoFocus /></Field>
              <Field label="Sobrenome"><Input value={sobrenome} onChange={(e) => setSobrenome(e.target.value)} /></Field>
            </div>
          )}
          {passo === 3 && (
            <div className="space-y-4">
              <Field label="Nome de usuário" hint="Usado no SSH e no sudo."><Input value={usuario} autoCapitalize="none" autoCorrect="off" spellCheck={false} onChange={(e) => { setUsuario(e.target.value); setMexeuUsuario(true) }} /></Field>
              <Field label="Sua senha"><Input type="password" value={senha} onChange={(e) => setSenha(e.target.value)} autoComplete="new-password" /></Field>
              <Field label="Confirmar a senha"><Input type="password" value={confirmacao} onChange={(e) => setConfirmacao(e.target.value)} autoComplete="new-password" /></Field>
            </div>
          )}
          {passo === 4 && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">Uma foto ajuda a identificar o dongle. É opcional — você pode adicionar depois no Perfil.</p>
              <div className="flex items-center gap-4">
                <div className="flex size-20 items-center justify-center overflow-hidden rounded-2xl bg-muted text-2xl font-semibold">
                  {foto ? <img src={foto} alt="Prévia" className="size-full object-cover" /> : (nome[0] ?? "?").toUpperCase()}
                </div>
                <label className="cursor-pointer">
                  <span className="inline-flex h-9 items-center gap-2 rounded-lg border border-border bg-secondary px-3 text-sm font-medium hover:bg-secondary/70">
                    <Camera className="size-4" /> {foto ? "Trocar foto" : "Escolher foto"}
                  </span>
                  <input type="file" accept="image/png,image/jpeg" className="hidden" onChange={(e) => escolherFoto(e.target.files?.[0])} />
                </label>
                {foto && <Btn size="sm" variant="ghost" onClick={() => setFoto("")}>Remover</Btn>}
              </div>
            </div>
          )}

          {erro && <Notice tone="warn">{erro}</Notice>}

          <div className="mt-6 flex items-center justify-between gap-2">
            {passo > 1 ? <Btn variant="ghost" onClick={() => { setErro(""); setPasso((p) => p - 1) }}><ArrowLeft className="size-4" /> Voltar</Btn> : <span />}
            {passo < PASSOS.length
              ? <Btn variant="primary" onClick={avancar}>Continuar <ArrowRight className="size-4" /></Btn>
              : <Btn variant="primary" onClick={concluir} disabled={enviando}><Check className="size-4" /> {enviando ? "Concluindo…" : "Concluir"}</Btn>}
          </div>
        </Card>
      </div>
    </div>
  )
}
