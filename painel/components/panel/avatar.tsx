"use client"

import { useEffect, useState } from "react"
import { Camera } from "lucide-react"
import { PERFIL, usePanel } from "@/lib/panel/store"
import { fotoParaDataUrl } from "@/lib/panel/foto"
import { cn } from "@/lib/utils"

const CORES = ["#3b6ef2", "#0ea5a4", "#8b5cf6", "#e0812f", "#d6455f", "#5b8c2a"]

function iniciais() {
  const n = (PERFIL.nome || PERFIL.usuario).trim().split(/\s+/)
  const s = (n[0]?.[0] ?? "") + (n.length > 1 ? n[n.length - 1][0] : "")
  return s.toUpperCase() || "U"
}
function cor() {
  let soma = 0
  for (const c of PERFIL.nome || PERFIL.usuario || "?") soma += c.charCodeAt(0)
  return CORES[soma % CORES.length]
}

// muda a cada upload/remoção pra furar o cache da <img src="/api/avatar">
let versao = 0
export function marcarAvatarMudou() {
  versao++
  if (typeof window !== "undefined") window.dispatchEvent(new Event("avatar-mudou"))
}
function useAvatarVersao() {
  const [, set] = useState(0)
  useEffect(() => {
    const h = () => set((v) => v + 1)
    window.addEventListener("avatar-mudou", h)
    return () => window.removeEventListener("avatar-mudou", h)
  }, [])
  return versao
}

export function Avatar({ size = 36, className }: { size?: number; className?: string }) {
  const v = useAvatarVersao()
  const src = PERFIL.foto ? `/api/avatar?v=${v}` : null
  return (
    <span
      className={cn("inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full", className)}
      style={{ width: size, height: size, background: src ? undefined : cor() }}
    >
      {src ? (
        <img src={src} alt="Foto" className="size-full object-cover" />
      ) : (
        <span className="font-semibold text-white" style={{ fontSize: size * 0.4 }}>{iniciais()}</span>
      )}
    </span>
  )
}

/** Avatar grande com upload — enviado ao dongle (não fica só no navegador). */
export function AvatarEditor() {
  const { processar } = usePanel()
  const v = useAvatarVersao()

  const escolher = async (file?: File) => {
    if (!file) return
    let foto: string
    try { foto = await fotoParaDataUrl(file) } catch { return }
    await processar({ mensagem: "Enviando a foto", duracao: 3000, acao: "avatar-set", args: { foto } })
    marcarAvatarMudou()
  }
  const remover = async () => {
    await processar({ mensagem: "Removendo a foto", duracao: 2000, acao: "avatar-rm" })
    marcarAvatarMudou()
  }

  return (
    <div className="flex items-center gap-4">
      <label className="group relative cursor-pointer rounded-full" aria-label="Trocar foto">
        <Avatar size={80} />
        <span className="absolute inset-0 flex items-center justify-center rounded-full bg-black/45 opacity-0 transition-opacity group-hover:opacity-100">
          <Camera className="size-5 text-white" />
        </span>
        <input type="file" accept="image/png,image/jpeg" className="sr-only" onChange={(e) => { escolher(e.target.files?.[0]); e.target.value = "" }} />
      </label>
      <div className="space-y-1">
        <div className="text-sm font-medium">Foto do perfil</div>
        <div className="flex gap-3 text-xs">
          <label className="cursor-pointer text-brand hover:underline">Enviar imagem
            <input type="file" accept="image/png,image/jpeg" className="sr-only" onChange={(e) => { escolher(e.target.files?.[0]); e.target.value = "" }} />
          </label>
          {PERFIL.foto && <button className="text-muted-foreground hover:text-foreground hover:underline" onClick={remover}>Remover</button>}
        </div>
      </div>
    </div>
  )
}
