"use client"

import { createContext, useContext, useEffect, useState, type ReactNode } from "react"

export type Idioma = "pt" | "en"

// idioma atual em nível de módulo: t() lê daqui, sem precisar de hook em cada
// componente. A troca remonta a árvore (key), então tudo re-renderiza no idioma
// novo. A 1ª pintura é sempre "pt" (bate com o HTML pré-renderizado do export
// estático); o efeito no cliente ajusta pro idioma detectado, sem erro de
// hidratação.
let idioma: Idioma = "pt"

/** t("texto em português", "text in English") — devolve o do idioma atual. */
export function t(pt: string, en: string): string {
  return idioma === "en" ? en : pt
}

export function getIdioma(): Idioma {
  return idioma
}

function detectar(): Idioma {
  try {
    const s = localStorage.getItem("idioma")
    if (s === "pt" || s === "en") return s
  } catch {}
  try {
    const c = document.cookie.match(/(?:^|;\s*)idioma=(pt|en)/)
    if (c) return c[1] as Idioma
  } catch {}
  try {
    return (navigator.language || "").toLowerCase().startsWith("pt") ? "pt" : "en"
  } catch {}
  return "pt"
}

const Ctx = createContext<{ lang: Idioma; trocar: (l: Idioma) => void }>({
  lang: "pt",
  trocar: () => {},
})

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Idioma>("pt")
  useEffect(() => {
    const l = detectar()
    idioma = l
    if (l !== lang) setLang(l)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const trocar = (l: Idioma) => {
    idioma = l
    try { localStorage.setItem("idioma", l) } catch {}
    try { document.cookie = `idioma=${l};path=/;max-age=31536000;samesite=strict` } catch {}
    setLang(l)
  }
  // key={lang}: trocar o idioma remonta a subárvore -> todo t() relê o módulo
  return (
    <Ctx.Provider value={{ lang, trocar }}>
      <div key={lang} style={{ display: "contents" }}>{children}</div>
    </Ctx.Provider>
  )
}

export function useIdioma() {
  return useContext(Ctx)
}
