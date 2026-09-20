"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { Search as SearchIcon, CornerDownLeft } from "lucide-react"
import { BUSCA, normaliza } from "@/lib/panel/nav"
import { t } from "@/lib/panel/i18n"

export function Search({ onNavigate }: { onNavigate?: () => void }) {
  const router = useRouter()
  const [q, setQ] = useState("")
  const [aberto, setAberto] = useState(false)
  const [ativo, setAtivo] = useState(0)
  const boxRef = useRef<HTMLDivElement>(null)

  const resultados = useMemo(() => {
    const termo = normaliza(q.trim())
    if (!termo) return []
    return BUSCA.filter((i) => {
      const alvo = normaliza(`${i.titulo} ${i.tituloEn} ${i.palavras}`)
      return termo.split(/\s+/).every((p) => alvo.includes(p))
    }).slice(0, 7)
  }, [q])

  useEffect(() => {
    const fora = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setAberto(false)
    }
    document.addEventListener("mousedown", fora)
    return () => document.removeEventListener("mousedown", fora)
  }, [])

  const ir = (rota: string) => {
    router.push(rota)
    setQ("")
    setAberto(false)
    onNavigate?.()
  }

  return (
    <div ref={boxRef} className="relative w-full max-w-md">
      <SearchIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
      <input
        value={q}
        onChange={(e) => {
          setQ(e.target.value)
          setAberto(true)
          setAtivo(0)
        }}
        onFocus={() => setAberto(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault()
            setAtivo((a) => Math.min(a + 1, resultados.length - 1))
          } else if (e.key === "ArrowUp") {
            e.preventDefault()
            setAtivo((a) => Math.max(a - 1, 0))
          } else if (e.key === "Enter" && resultados[ativo]) {
            e.preventDefault()
            ir(resultados[ativo].rota)
          } else if (e.key === "Escape") {
            setAberto(false)
          }
        }}
        placeholder={t("Buscar configurações...", "Search settings...")}
        className="h-9 w-full rounded-lg border border-border bg-background pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground/70 focus-visible:border-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/20"
      />
      {aberto && resultados.length > 0 ? (
        <ul className="absolute left-0 right-0 top-11 z-50 overflow-hidden rounded-xl border border-border bg-popover p-1 shadow-lg">
          {resultados.map((r, i) => (
            <li key={r.rota}>
              <button
                onMouseEnter={() => setAtivo(i)}
                onClick={() => ir(r.rota)}
                className={`flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                  i === ativo ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted"
                }`}
              >
                <span className="truncate text-foreground">{t(r.titulo, r.tituloEn)}</span>
                {i === ativo ? <CornerDownLeft className="size-3.5 shrink-0 text-muted-foreground" /> : null}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {aberto && q.trim() && resultados.length === 0 ? (
        <div className="absolute left-0 right-0 top-11 z-50 rounded-xl border border-border bg-popover px-3 py-3 text-sm text-muted-foreground shadow-lg">
          {t("Nada encontrado para", "No results for")} “{q}”.
        </div>
      ) : null}
    </div>
  )
}
