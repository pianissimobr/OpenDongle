"use client"

import { useState } from "react"
import { CircleDot, ArrowRight, ArrowLeft, Check, Camera } from "lucide-react"
import { Card, Field, Input, Btn, Notice } from "@/components/panel/ui"
import { fotoParaDataUrl } from "@/lib/panel/foto"
import { t } from "@/lib/panel/i18n"
import { LangCorner } from "@/components/panel/lang-corner"

const PASSOS: [string, string][] = [
  ["Senha do sistema", "System password"],
  ["Seu nome", "Your name"],
  ["Seu acesso", "Your access"],
  ["Sua foto", "Your photo"],
]

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
      if (senhaRoot.length < 6) return t("A senha do sistema precisa de ao menos 6 caracteres.", "The system password needs at least 6 characters.")
      if (senhaRoot === "1") return t("Escolha uma senha diferente da de fábrica.", "Choose a password different from the factory one.")
    }
    if (passo === 2) {
      if (!nome.trim() || !sobrenome.trim()) return t("Informe nome e sobrenome.", "Enter first and last name.")
    }
    if (passo === 3) {
      if (!/^[a-z][a-z0-9_-]{2,31}$/.test(usuario)) return t("Usuário: minúsculas, números, - ou _ (começa por letra).", "Username: lowercase letters, numbers, - or _ (starts with a letter).")
      if (senha.length < 6) return t("A sua senha precisa de ao menos 6 caracteres.", "Your password needs at least 6 characters.")
      if (senha !== confirmacao) return t("As duas senhas não são iguais.", "The two passwords don't match.")
      if (senha === senhaRoot) return t("Use uma senha diferente da senha do sistema.", "Use a password different from the system password.")
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
    try { setFoto(await fotoParaDataUrl(file)) } catch { setErro(t("Não consegui ler essa imagem.", "I couldn't read that image.")) }
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
      else { setErro(d.erro || t("Não foi possível concluir o cadastro.", "Could not complete the sign-up.")); if (d.etapa) setPasso(d.etapa); setEnviando(false) }
    } catch { setErro(t("Não foi possível falar com o dongle.", "Could not reach the dongle.")); setEnviando(false) }
  }

  return (
    <div className="relative flex min-h-svh items-center justify-center bg-background px-4 py-8">
      <LangCorner />
      <div className="w-full max-w-md">
        <div className="mb-6 flex flex-col items-center gap-2.5 text-center">
          <span className="flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <CircleDot className="size-6" />
          </span>
          <h1 className="text-lg font-semibold tracking-tight">{t("Bem-vindo ao OpenDongle", "Welcome to OpenDongle")}</h1>
          <p className="text-sm text-muted-foreground">{t("Vamos configurar o seu dongle. Leva um minuto.", "Let's set up your dongle. It takes a minute.")}</p>
        </div>

        <div className="mb-4 flex items-center gap-2">
          {PASSOS.map((_, i) => (
            <span key={i} className={`h-1.5 flex-1 rounded-full ${i + 1 <= passo ? "bg-brand" : "bg-muted"}`} />
          ))}
        </div>

        <Card>
          <p className="mb-1 text-xs font-medium text-muted-foreground">{t(`Passo ${passo} de ${PASSOS.length}`, `Step ${passo} of ${PASSOS.length}`)}</p>
          <h2 className="mb-4 text-base font-semibold">{t(...PASSOS[passo - 1])}</h2>

          {passo === 1 && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">{t("A senha de administração do sistema (root). Guarde-a: é a chave de recuperação se você esquecer a sua senha.", "The system's admin password (root). Keep it safe: it's the recovery key if you forget your password.")}</p>
              <Field label={t("Senha do sistema (root)", "System password (root)")}><Input type="password" value={senhaRoot} onChange={(e) => setSenhaRoot(e.target.value)} autoFocus /></Field>
            </div>
          )}
          {passo === 2 && (
            <div className="space-y-4">
              <Field label={t("Nome", "First name")}><Input value={nome} onChange={(e) => setNome(e.target.value)} autoFocus /></Field>
              <Field label={t("Sobrenome", "Last name")}><Input value={sobrenome} onChange={(e) => setSobrenome(e.target.value)} /></Field>
            </div>
          )}
          {passo === 3 && (
            <div className="space-y-4">
              <Field label={t("Nome de usuário", "Username")} hint={t("Usado no SSH e no sudo.", "Used for SSH and sudo.")}><Input value={usuario} autoCapitalize="none" autoCorrect="off" spellCheck={false} onChange={(e) => { setUsuario(e.target.value); setMexeuUsuario(true) }} /></Field>
              <Field label={t("Sua senha", "Your password")}><Input type="password" value={senha} onChange={(e) => setSenha(e.target.value)} autoComplete="new-password" /></Field>
              <Field label={t("Confirmar a senha", "Confirm the password")}><Input type="password" value={confirmacao} onChange={(e) => setConfirmacao(e.target.value)} autoComplete="new-password" /></Field>
            </div>
          )}
          {passo === 4 && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">{t("Uma foto ajuda a identificar o dongle. É opcional — você pode adicionar depois no Perfil.", "A photo helps identify the dongle. It's optional — you can add it later in Profile.")}</p>
              <div className="flex items-center gap-4">
                <div className="flex size-20 items-center justify-center overflow-hidden rounded-2xl bg-muted text-2xl font-semibold">
                  {foto ? <img src={foto} alt={t("Prévia", "Preview")} className="size-full object-cover" /> : (nome[0] ?? "?").toUpperCase()}
                </div>
                <label className="cursor-pointer">
                  <span className="inline-flex h-9 items-center gap-2 rounded-lg border border-border bg-secondary px-3 text-sm font-medium hover:bg-secondary/70">
                    <Camera className="size-4" /> {foto ? t("Trocar foto", "Change photo") : t("Escolher foto", "Choose photo")}
                  </span>
                  <input type="file" accept="image/png,image/jpeg" className="hidden" onChange={(e) => escolherFoto(e.target.files?.[0])} />
                </label>
                {foto && <Btn size="sm" variant="ghost" onClick={() => setFoto("")}>{t("Remover", "Remove")}</Btn>}
              </div>
            </div>
          )}

          {erro && <Notice tone="warn">{erro}</Notice>}

          <div className="mt-6 flex items-center justify-between gap-2">
            {passo > 1 ? <Btn variant="ghost" onClick={() => { setErro(""); setPasso((p) => p - 1) }}><ArrowLeft className="size-4" /> {t("Voltar", "Back")}</Btn> : <span />}
            {passo < PASSOS.length
              ? <Btn variant="primary" onClick={avancar}>{t("Continuar", "Continue")} <ArrowRight className="size-4" /></Btn>
              : <Btn variant="primary" onClick={concluir} disabled={enviando}><Check className="size-4" /> {enviando ? t("Concluindo…", "Finishing…") : t("Concluir", "Finish")}</Btn>}
          </div>
        </Card>
      </div>
    </div>
  )
}
