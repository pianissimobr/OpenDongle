"use client"

import { useEffect, useState } from "react"
import { Sun, Moon } from "lucide-react"

type Tema = "claro" | "escuro" | "auto"

function aplica(t: Tema) {
  const el = document.documentElement
  el.classList.remove("dark", "light")
  if (t === "escuro") el.classList.add("dark")
  else if (t === "claro") el.classList.add("light")
}

export function ThemeToggle() {
  const [tema, setTema] = useState<Tema>("auto")

  useEffect(() => {
    const salvo = (localStorage.getItem("tema-ux") as Tema) || "auto"
    setTema(salvo)
  }, [])

  const alterna = () => {
    const escuroAtivo = document.documentElement.classList.contains("dark") ||
      (!document.documentElement.classList.contains("light") &&
        window.matchMedia("(prefers-color-scheme: dark)").matches)
    const novo: Tema = escuroAtivo ? "claro" : "escuro"
    setTema(novo)
    localStorage.setItem("tema-ux", novo)
    aplica(novo)
  }

  return (
    <button
      type="button"
      onClick={alterna}
      aria-label="Alternar tema"
      className="flex size-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
    >
      <Sun className="size-4.5 dark:hidden" />
      <Moon className="hidden size-4.5 dark:block" />
      <span className="sr-only">Alternar tema {tema}</span>
    </button>
  )
}
