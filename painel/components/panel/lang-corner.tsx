"use client"

import { Globe } from "lucide-react"
import { useIdioma, type Idioma } from "@/lib/panel/i18n"

/** Seletor de idioma solto no canto — para as telas sem sidebar (login, cadastro). */
export function LangCorner() {
  const { lang, trocar } = useIdioma()
  const outro: Idioma = lang === "pt" ? "en" : "pt"
  return (
    <button
      onClick={() => trocar(outro)}
      className="absolute right-4 top-4 flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      title={lang === "pt" ? "Switch language" : "Trocar idioma"}
    >
      <Globe className="size-3.5" />
      {outro === "pt" ? "PT" : "EN"}
    </button>
  )
}
