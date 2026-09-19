"use client"

import { usePanel } from "@/lib/panel/store"

export function ProcessOverlay() {
  const { overlay } = usePanel()
  if (!overlay?.ativo) return null
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-background/70 backdrop-blur-sm">
      <div className="mx-4 w-full max-w-sm rounded-2xl border border-border bg-card p-6 text-center shadow-xl">
        <div className="mx-auto mb-4 size-8 animate-spin rounded-full border-2 border-muted border-t-brand" />
        <div className="text-sm font-medium text-foreground">{overlay.mensagem}</div>
        {overlay.detalhe ? <div className="mt-1 text-xs text-muted-foreground">{overlay.detalhe}</div> : null}
        <div className="mt-4 h-1 overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-brand"
            style={{ animation: `barra ${overlay.duracao}ms linear forwards` }}
          />
        </div>
      </div>
      <style>{`@keyframes barra { from { width: 0% } to { width: 100% } }`}</style>
    </div>
  )
}
