"use client"

import Link from "next/link"
import { ChevronRight, type LucideIcon } from "lucide-react"
import type { ComponentProps, ReactNode } from "react"
import { cn } from "@/lib/utils"

/* ---------- Cabeçalho de página ---------- */

export function PageHeader({
  icon: Icon,
  title,
  desc,
  children,
}: {
  icon?: LucideIcon
  title: string
  desc?: ReactNode
  children?: ReactNode
}) {
  return (
    <header className="flex flex-col gap-3 border-b border-border pb-5 sm:flex-row sm:items-start sm:justify-between">
      <div className="flex items-start gap-3">
        {Icon ? (
          <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
            <Icon className="size-4.5" />
          </span>
        ) : null}
        <div className="min-w-0">
          <h1 className="text-balance text-xl font-semibold tracking-tight">{title}</h1>
          {desc ? <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{desc}</p> : null}
        </div>
      </div>
      {children ? <div className="flex shrink-0 items-center gap-2">{children}</div> : null}
    </header>
  )
}

/* ---------- Cartão / seção ---------- */

export function Card({
  className,
  children,
  ...props
}: ComponentProps<"section">) {
  return (
    <section
      className={cn("rounded-xl border border-border bg-card p-5", className)}
      {...props}
    >
      {children}
    </section>
  )
}

export function CardTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mb-4 flex items-baseline justify-between gap-3">
      <h2 className="text-sm font-semibold tracking-tight">{children}</h2>
      {hint ? <span className="text-xs text-muted-foreground">{hint}</span> : null}
    </div>
  )
}

/* ---------- Linha de lista (navegável ou estática) ---------- */

export function Row({
  icon: Icon,
  title,
  sub,
  href,
  action,
  className,
}: {
  icon?: LucideIcon
  title: ReactNode
  sub?: ReactNode
  href?: string
  action?: ReactNode
  className?: string
}) {
  const inner = (
    <>
      {Icon ? (
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground group-hover:text-foreground">
          <Icon className="size-4.5" />
        </span>
      ) : null}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-foreground">{title}</span>
        {sub ? <span className="mt-0.5 block truncate text-xs text-muted-foreground">{sub}</span> : null}
      </span>
      {href ? (
        <ChevronRight className="size-4 shrink-0 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5" />
      ) : action ? (
        <span className="flex shrink-0 flex-wrap items-center justify-end gap-2">{action}</span>
      ) : null}
    </>
  )

  const base = "group flex items-center gap-3 rounded-lg px-2.5 py-2.5 transition-colors"

  if (href) {
    return (
      <Link href={href} className={cn(base, "hover:bg-muted", className)}>
        {inner}
      </Link>
    )
  }
  return <div className={cn(base, className)}>{inner}</div>
}

/** Grupo de linhas com divisórias sutis. */
export function RowGroup({ children, cols = 1 }: { children: ReactNode; cols?: 1 | 2 }) {
  return (
    <div
      className={cn(
        "-mx-1 divide-y divide-border",
        cols === 2 && "sm:grid sm:grid-cols-2 sm:gap-x-6 sm:divide-y-0 [&>*]:border-b [&>*]:border-border",
      )}
    >
      {children}
    </div>
  )
}

/* ---------- Pílula de status ---------- */

const TONE: Record<string, string> = {
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  err: "bg-err-soft text-err",
  neutral: "bg-muted text-muted-foreground",
  brand: "bg-brand/10 text-brand",
}

export function Pill({
  tone = "neutral",
  children,
  className,
}: {
  tone?: keyof typeof TONE | string
  children: ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
        TONE[tone] ?? TONE.neutral,
        className,
      )}
    >
      {children}
    </span>
  )
}

/* ---------- Tile de estatística ---------- */

export function Stat({
  label,
  value,
  tone,
  bar,
}: {
  label: ReactNode
  value: ReactNode
  tone?: "" | "warn" | "err"
  bar?: number | null
}) {
  const color = tone === "err" ? "text-err" : tone === "warn" ? "text-warn" : "text-foreground"
  const barColor = tone === "err" ? "bg-err" : tone === "warn" ? "bg-warn" : "bg-ok"
  return (
    <div className="rounded-lg border border-border bg-background p-3.5">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-1 text-2xl font-semibold tabular-nums transition-colors", color)}>{value}</div>
      {bar != null ? (
        <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-muted">
          <div
            className={cn("h-full rounded-full transition-all duration-500", barColor)}
            style={{ width: `${Math.min(Math.max(bar, 0), 100)}%` }}
          />
        </div>
      ) : null}
    </div>
  )
}

/* ---------- Barra fina ---------- */

export function MiniBar({ value, tone = "brand" }: { value: number; tone?: "brand" | "ok" | "warn" | "err" }) {
  const color = { brand: "bg-brand", ok: "bg-ok", warn: "bg-warn", err: "bg-err" }[tone]
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-muted">
      <div className={cn("h-full rounded-full transition-all duration-500", color)} style={{ width: `${Math.min(Math.max(value, 0), 100)}%` }} />
    </div>
  )
}

/* ---------- Botão ---------- */

type BtnVariant = "primary" | "secondary" | "ghost" | "danger"

const BTN: Record<BtnVariant, string> = {
  primary: "bg-primary text-primary-foreground hover:bg-primary/90",
  secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/70 border border-border",
  ghost: "text-foreground hover:bg-muted",
  danger: "bg-err-soft text-err hover:bg-err/15",
}

export function Btn({
  variant = "secondary",
  size = "md",
  className,
  ...props
}: ComponentProps<"button"> & { variant?: BtnVariant; size?: "sm" | "md" }) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-xs" : "h-10 px-4 text-sm",
        BTN[variant],
        className,
      )}
      {...props}
    />
  )
}

/* ---------- Campo de formulário ---------- */

export function Field({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-muted-foreground">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-xs text-muted-foreground">{hint}</span> : null}
    </label>
  )
}

const CONTROL =
  "w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground transition-colors placeholder:text-muted-foreground/70 focus-visible:border-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/20"

export function Input({ className, ...props }: ComponentProps<"input">) {
  return <input className={cn(CONTROL, "h-10", className)} {...props} />
}

export function Select({ className, ...props }: ComponentProps<"select">) {
  return <select className={cn(CONTROL, "h-10", className)} {...props} />
}

export function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return <textarea className={cn(CONTROL, "py-2.5", className)} {...props} />
}

/* ---------- Toggle switch ---------- */

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: ReactNode
}) {
  return (
    <label className="flex cursor-pointer items-center gap-3 py-1.5 text-sm">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors",
          checked ? "bg-brand" : "bg-muted",
        )}
      >
        <span
          className={cn(
            "inline-block size-4 rounded-full bg-background shadow-sm transition-transform",
            checked ? "translate-x-4" : "translate-x-0.5",
          )}
        />
      </button>
      <span className="text-foreground">{label}</span>
    </label>
  )
}

/* ---------- Aviso ---------- */

export function Notice({ children, tone = "warn" }: { children: ReactNode; tone?: "warn" | "info" }) {
  return (
    <div
      className={cn(
        "rounded-lg border px-3.5 py-3 text-xs leading-relaxed",
        tone === "warn" ? "border-warn/30 bg-warn-soft/50 text-warn" : "border-border bg-muted/50 text-muted-foreground",
      )}
    >
      {children}
    </div>
  )
}

/* ---------- Mensagem de resultado ---------- */

export function Msg({ children, tone = "ok" }: { children: ReactNode; tone?: "ok" | "err" }) {
  if (!children) return null
  return (
    <div
      className={cn(
        "rounded-lg px-3.5 py-2.5 text-sm",
        tone === "ok" ? "bg-ok-soft text-ok" : "bg-err-soft text-err",
      )}
    >
      {children}
    </div>
  )
}

/* ---------- Segmented control ---------- */

export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T
  options: { value: T; label: ReactNode }[]
  onChange: (v: T) => void
}) {
  return (
    <div className="inline-flex rounded-lg border border-border bg-muted/50 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
            value === o.value ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
