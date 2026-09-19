"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useState, type ReactNode } from "react"
import { Menu, X, LogOut, Wifi, Radio, ChevronDown, CircleDot } from "lucide-react"
import { CATEGORIAS, CAT_AJUDA, CAT_AVANCADAS, CATEGORIA_DA_ROTA } from "@/lib/panel/nav"
import { CatIcon } from "./icon"
import { Search } from "./search"
import { ThemeToggle } from "./theme"
import { Avatar } from "./avatar"
import { ProcessOverlay } from "./overlay"
import { ESTADOS, PERFIL, usePanel } from "@/lib/panel/store"
import { cn } from "@/lib/utils"

function Marca() {
  return (
    <Link href="/" className="flex items-center gap-2.5">
      <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <CircleDot className="size-4.5" />
      </span>
      <span className="text-[15px] font-semibold tracking-tight">OpenDongle</span>
    </Link>
  )
}

function NavItem({ rota, ativo, children }: { rota: string; ativo: boolean; children: ReactNode }) {
  return (
    <Link
      href={rota}
      className={cn(
        "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
        ativo ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      {children}
    </Link>
  )
}

function EstadoChip() {
  const { estado } = usePanel()
  const online = estado.internet
  const Icon = estado.modo === "wifi" ? Wifi : Radio
  return (
    <div className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-xs">
      <Icon className={cn("size-4", online ? "text-ok" : "text-warn")} />
      <span className="min-w-0 flex-1 truncate text-muted-foreground">
        {estado.modo === "wifi" ? estado.endereco?.ssid ?? "Wi-Fi" : estado.ssidHotspot ?? "Hotspot"}
      </span>
      <span className={cn("size-1.5 rounded-full", online ? "bg-ok" : "bg-warn")} />
    </div>
  )
}

function DebugSwitcher() {
  const { estadoNome, setEstado, avancadas, setAvancadas } = usePanel()
  const [aberto, setAberto] = useState(false)
  return (
    <div className="rounded-lg border border-dashed border-border">
      <button
        onClick={() => setAberto((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-xs font-medium text-muted-foreground"
      >
        <span>Simulação (protótipo)</span>
        <ChevronDown className={cn("size-3.5 transition-transform", aberto && "rotate-180")} />
      </button>
      {aberto ? (
        <div className="space-y-2 border-t border-border p-3">
          <select
            value={estadoNome}
            onChange={(e) => setEstado(e.target.value)}
            className="h-8 w-full rounded-md border border-border bg-background px-2 text-xs"
          >
            {Object.entries(ESTADOS).map(([k, v]) => (
              <option key={k} value={k}>
                {v.rotulo}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input type="checkbox" checked={avancadas} onChange={(e) => setAvancadas(e.target.checked)} />
            Mostrar configurações avançadas
          </label>
        </div>
      ) : null}
    </div>
  )
}

function SidebarConteudo({ ativoId, onNavigate }: { ativoId: string; onNavigate?: () => void }) {
  const { avancadas } = usePanel()
  return (
    <div className="flex h-full flex-col">
      <div className="px-4 pb-4 pt-5">
        <Marca />
      </div>
      <nav className="flex-1 space-y-1 overflow-y-auto px-3" onClick={onNavigate}>
        {CATEGORIAS.map((c) => (
          <NavItem key={c.id} rota={c.rota} ativo={ativoId === c.id}>
            <CatIcon name={c.icon} className="size-4.5" />
            {c.nome}
          </NavItem>
        ))}
        <div className="my-2 border-t border-border" />
        <NavItem rota={CAT_AJUDA.rota} ativo={ativoId === CAT_AJUDA.id}>
          <CatIcon name={CAT_AJUDA.icon} className="size-4.5" />
          {CAT_AJUDA.nome}
        </NavItem>
        {avancadas ? (
          <NavItem rota={CAT_AVANCADAS.rota} ativo={ativoId === CAT_AVANCADAS.id}>
            <CatIcon name={CAT_AVANCADAS.icon} className="size-4.5" />
            {CAT_AVANCADAS.nome}
          </NavItem>
        ) : null}
      </nav>
      <div className="space-y-3 border-t border-border p-3">
        <EstadoChip />
        <DebugSwitcher />
        <Link
          href="/perfil"
          onClick={onNavigate}
          className="flex items-center gap-3 rounded-lg px-1.5 py-1.5 transition-colors hover:bg-muted"
        >
          <Avatar size={36} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{PERFIL.nome}</span>
            <span className="block truncate text-xs text-muted-foreground">Administrador</span>
          </span>
          <LogOut className="size-4 text-muted-foreground" />
        </Link>
      </div>
    </div>
  )
}

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  const [drawer, setDrawer] = useState(false)
  const ativoId = CATEGORIA_DA_ROTA[pathname] ?? "inicio"

  useEffect(() => {
    setDrawer(false)
  }, [pathname])

  // login é pré-autenticação: sem sidebar, busca ou avatar
  if (pathname === "/login" || pathname === "/cadastro") return <>{children}</>

  return (
    <div className="min-h-svh bg-background">
      {/* Sidebar desktop */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 border-r border-border bg-card lg:block">
        <SidebarConteudo ativoId={ativoId} />
      </aside>

      {/* Drawer mobile */}
      {drawer ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setDrawer(false)} />
          <div className="absolute inset-y-0 left-0 w-72 max-w-[85vw] border-r border-border bg-card">
            <button
              onClick={() => setDrawer(false)}
              className="absolute right-3 top-4 flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted"
              aria-label="Fechar menu"
            >
              <X className="size-4.5" />
            </button>
            <SidebarConteudo ativoId={ativoId} onNavigate={() => setDrawer(false)} />
          </div>
        </div>
      ) : null}

      <div className="lg:pl-64">
        {/* Top bar */}
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border bg-background/85 px-4 backdrop-blur sm:px-6">
          <button
            onClick={() => setDrawer(true)}
            className="flex size-9 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted lg:hidden"
            aria-label="Abrir menu"
          >
            <Menu className="size-5" />
          </button>
          <div className="flex-1">
            <Search onNavigate={() => setDrawer(false)} />
          </div>
          <ThemeToggle />
          <Link href="/perfil" className="lg:hidden">
            <Avatar size={32} />
          </Link>
        </header>

        <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:py-8">{children}</main>
      </div>

      <ProcessOverlay />
    </div>
  )
}
