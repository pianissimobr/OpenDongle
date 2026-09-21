"use client"

import Link from "next/link"
import { useState, useEffect, useRef } from "react"
import {
  Activity, AudioLines, CalendarClock, Check, CircleHelp, Cpu, Database,
  FileJson, HardDrive, KeyRound, Lightbulb, ListTree, LockKeyhole,
  MemoryStick, Network, RefreshCw, Router, Search, Server, Settings2,
  ShieldCheck, Stethoscope, Terminal, Thermometer, UserRound, Wifi,
  Wrench, Zap, Bluetooth, Usb, Volume2, Radio, Clock3, Download,
} from "lucide-react"
import { Card, CardTitle, Field, Input, Select, Textarea, Btn, Notice, Pill, Row, RowGroup, Stat, MiniBar, Toggle, Segmented, PageHeader, Msg } from "@/components/panel/ui"
import { usePanel, PERFIL, apiGet, type ResultadoAcao, type Servico } from "@/lib/panel/store"
import { t } from "@/lib/panel/i18n"
import { AvatarEditor } from "@/components/panel/avatar"
import { cn } from "@/lib/utils"

const icons: Record<string, typeof Wifi> = {
  perfil: UserRound, senha: KeyRound, dispositivos: Usb, bluetooth: Bluetooth, usb: Usb,
  audio: Volume2, leds: Lightbulb, sistema: Settings2, hora: Clock3,
  atualizacoes: Download, status: Activity, desempenho: Cpu, espaco: HardDrive,
  hardware: Router, "nome-backup": Database, ajuda: CircleHelp, avancadas: Wrench,
  logs: Terminal, diagnostico: Stethoscope, kernel: Server, recursos: MemoryStick,
  "config-arquivo": FileJson, firewall: ShieldCheck, remoto: Network, tor: Radio,
}

const groups = {
  perfil: {
    title: ["Perfil", "Profile"], desc: ["Sua conta, senha e foto de administrador.", "Your account, password and admin photo."],
    items: [
      ["/perfil", ["Conta e identidade", "Account and identity"], ["Nome, usuário e foto do administrador", "Name, username and admin photo"]],
      ["/senha", ["Senha de acesso", "Access password"], ["Trocar a senha e encerrar outras sessões", "Change the password and end other sessions"]],
    ],
  },
  dispositivos: {
    title: ["Dispositivos", "Devices"], desc: ["Bluetooth, USB, áudio e luzes do aparelho.", "Bluetooth, USB, audio and the device's lights."],
    items: [
      ["/bluetooth", ["Bluetooth", "Bluetooth"], ["Parear fones, caixas e outros aparelhos", "Pair headsets, speakers and other devices"]],
      ["/usb", ["Aparelhos USB", "USB devices"], ["Escolher o papel da porta e ver aparelhos conectados", "Choose the port role and see connected devices"]],
      ["/audio", ["Áudio", "Audio"], ["Placas, volume, microfone e saídas Bluetooth", "Sound cards, volume, microphone and Bluetooth outputs"]],
      ["/leds", ["LEDs", "LEDs"], ["Definir como as luzes do dongle se comportam", "Set how the dongle's lights behave"]],
    ],
  },
  sistema: {
    title: ["Sistema", "System"], desc: ["Atualizações, hora, espaço, hardware e backup.", "Updates, time, space, hardware and backup."],
    items: [
      ["/hora", ["Data e hora", "Date and time"], ["Relógio, fuso horário e sincronização", "Clock, time zone and synchronization"]],
      ["/atualizacoes", ["Atualizações", "Updates"], ["Ver e instalar atualizações disponíveis", "Check and install available updates"]],
      ["/status", ["Status e saúde", "Status and health"], ["Temperatura, memória e armazenamento", "Temperature, memory and storage"]],
      ["/desempenho", ["Desempenho", "Performance"], ["CPU, RAM e processos em execução", "CPU, RAM and running processes"]],
      ["/espaco", ["Espaço em disco", "Disk space"], ["Uso do armazenamento e limpeza", "Storage usage and cleanup"]],
      ["/hardware", ["Hardware", "Hardware"], ["Placa, memória, eMMC, IMEI e MAC", "Board, memory, eMMC, IMEI and MAC"]],
      ["/nome-backup", ["Nome, backup e reset", "Name, backup and reset"], ["Nome do dongle, cópia e restauração", "Dongle name, backup and restore"]],
    ],
  },
  ajuda: {
    title: ["Ajuda e recuperação", "Help and recovery"], desc: ["Perdi o acesso, como recuperar e dúvidas comuns.", "Lost access, how to recover, and common questions."],
    items: [
      ["/ajuda#senha", ["Esqueci a senha", "I forgot the password"], ["Como recuperar pelo root ou pelo cabo USB", "How to recover via root or the USB cable"]],
      ["/ajuda#wifi", ["Não consigo conectar no Wi-Fi", "I can't connect to Wi-Fi"], ["Verifique senha, sinal e o endereço novo", "Check the password, signal and the new address"]],
      ["/ajuda#4g", ["Chip 4G não conecta", "4G SIM won't connect"], ["APN, sinal, registro e crédito", "APN, signal, registration and credit"]],
    ],
  },
  avancadas: {
    title: ["Opções avançadas", "Advanced options"], desc: ["Ferramentas para investigar e operar o sistema.", "Tools to inspect and operate the system."],
    items: [
      ["/logs", ["Logs do sistema", "System logs"], ["journalctl por serviço", "journalctl per service"]],
      ["/diagnostico", ["Diagnóstico de hardware", "Hardware diagnostics"], ["Áudio, Bluetooth, vídeo USB e modem", "Audio, Bluetooth, USB video and modem"]],
      ["/recursos", ["Memória por serviço", "Memory per service"], ["RAM de cada serviço (PSS)", "RAM of each service (PSS)"]],
      ["/servicos", ["Serviços do sistema", "System services"], ["O que sobe no boot: ligar e desligar", "What starts at boot: on and off"]],
      ["/kernel", ["Kernel e módulos", "Kernel and modules"], ["Versão, parâmetros de boot e módulos", "Version, boot parameters and modules"]],
      ["/config-arquivo", ["Arquivo de configuração", "Configuration file"], ["A config central, com senhas ocultas", "The central config, with passwords hidden"]],
    ],
  },
} as const

type Item = readonly [string, string, string]

function GoBack() { return <Link href="/" className="text-xs text-muted-foreground hover:text-foreground">{t("← Voltar ao início", "← Back to home")}</Link> }
function Action({ label, message }: { label: string; message?: string }) {
  const msg = message ?? t("Aplicando configuração", "Applying configuration")
  const { processar } = usePanel()
  return <Btn size="sm" onClick={() => processar({ mensagem: msg, duracao: 700 })}>{label}</Btn>
}
function ListPage({ group }: { group: keyof typeof groups }) {
  const data = groups[group]
  const Icon = icons[group]
  return <div className="space-y-6"><PageHeader icon={Icon} title={t(...(data.title as unknown as [string, string]))} desc={t(...(data.desc as unknown as [string, string]))}><GoBack /></PageHeader><Card><RowGroup cols={2}>{(data.items as unknown as [string, [string, string], [string, string]][]).map(([href, title, sub]) => <Row key={href} href={href} icon={icons[href.slice(1)] ?? ListTree} title={t(...title)} sub={t(...sub)} />)}</RowGroup></Card></div>
}

function Perfil({ password = false }: { password?: boolean }) {
  const { processar } = usePanel()
  const [atual, setAtual] = useState("")
  const [nova, setNova] = useState("")
  const [conf, setConf] = useState("")
  const [encerrar, setEncerrar] = useState(false)
  const [msg, setMsg] = useState<{ tone: "info" | "warn"; texto: string } | null>(null)
  const [novoUser, setNovoUser] = useState("")
  const [senhaRenom, setSenhaRenom] = useState("")
  const [msgUser, setMsgUser] = useState<{ tone: "info" | "warn"; texto: string } | null>(null)
  const renomear = async () => {
    setMsgUser(null)
    if (!/^[a-z][a-z0-9_-]{2,31}$/.test(novoUser)) { setMsgUser({ tone: "warn", texto: t("Use minúsculas, números, - ou _ (começando por letra).", "Use lowercase letters, numbers, - or _ (starting with a letter).") }); return }
    await processar({ mensagem: t("Trocando o nome de usuário", "Changing the username"), duracao: 8000, acao: "usuario-renomear", args: { atual: senhaRenom, novo: novoUser } })
    setSenhaRenom("")
    setMsgUser({ tone: "info", texto: t("Se a senha estava certa, o usuário foi renomeado. As sessões SSH caem.", "If the password was right, the user was renamed. SSH sessions will drop.") })
  }

  const trocar = async () => {
    setMsg(null)
    if (nova !== conf) { setMsg({ tone: "warn", texto: t("As duas senhas novas não são iguais.", "The two new passwords don't match.") }); return }
    if (nova.length < 8) { setMsg({ tone: "warn", texto: t("Use pelo menos 8 caracteres.", "Use at least 8 characters.") }); return }
    await processar({
      mensagem: t("Trocando a senha", "Changing the password"), duracao: 4000,
      acao: "set-password", args: { atual, nova, confirmacao: conf, encerrar },
    })
    setAtual(""); setNova(""); setConf("")
    setMsg({ tone: "info", texto: t("Se a senha atual estava certa, a senha foi trocada.", "If the current password was right, the password was changed.") })
  }


  return <div className="space-y-6"><PageHeader icon={password ? KeyRound : UserRound} title={password ? t("Senha de acesso", "Access password") : t("Conta e identidade", "Account and identity")} desc={password ? t("Uma senha forte protege o painel e o acesso administrativo.", "A strong password protects the panel and admin access.") : t("Identidade usada para administrar este dongle.", "Identity used to administer this dongle.")}><GoBack /></PageHeader><Card><CardTitle>{password ? t("Trocar senha", "Change password") : t("Administrador", "Administrator")}</CardTitle>{password ? <div className="max-w-xl space-y-4"><Field label={t("Senha atual", "Current password")}><Input type="password" value={atual} onChange={(e) => setAtual(e.target.value)} autoComplete="current-password" /></Field><Field label={t("Nova senha", "New password")} hint={t("Use pelo menos 8 caracteres.", "Use at least 8 characters.")}><Input type="password" value={nova} onChange={(e) => setNova(e.target.value)} autoComplete="new-password" /></Field><Field label={t("Confirmar nova senha", "Confirm new password")}><Input type="password" value={conf} onChange={(e) => setConf(e.target.value)} autoComplete="new-password" /></Field><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={encerrar} onChange={(e) => setEncerrar(e.target.checked)} /> {t("Encerrar outras sessões", "End other sessions")}</label><Btn variant="primary" onClick={trocar} disabled={!atual || !nova}>{t("Trocar senha", "Change password")}</Btn>{msg && <Notice tone={msg.tone}>{msg.tone === "info" && <Check className="mr-1 inline size-3.5" />}{msg.texto}</Notice>}</div> : <div className="space-y-5"><AvatarEditor /><div><p className="text-lg font-semibold">{PERFIL.nome || PERFIL.usuario}</p><p className="text-sm text-muted-foreground">@{PERFIL.usuario} · {t("Administrador", "Administrator")}</p></div></div>}</Card></div>
}

function UsbPage() { const { dados, processar } = usePanel(); return <div className="space-y-6"><PageHeader icon={Usb} title={t("Aparelhos USB", "USB devices")} desc={t("Escolha como a porta USB do dongle deve funcionar.", "Choose how the dongle's USB port should work.")}><GoBack /></PageHeader><Card><CardTitle>{t("Papel da porta", "Port role")}</CardTitle><div className="grid gap-3 sm:grid-cols-2"><button onClick={() => processar({ mensagem: t("Mudando a porta USB para host", "Switching the USB port to host"), duracao: 3000, acao: "usb-papel", args: { papel: "host" } })} className={cn("rounded-xl border p-4 text-left", dados.usb.papel === "host" && "border-brand bg-brand/5")}><p className="font-medium">Host</p><p className="mt-1 text-xs text-muted-foreground">{t("Conectar pendrive, teclado ou placa de som.", "Connect a flash drive, keyboard or sound card.")}</p></button><button onClick={() => processar({ mensagem: t("Mudando a porta USB para device", "Switching the USB port to device"), duracao: 3000, acao: "usb-papel", args: { papel: "device" } })} className={cn("rounded-xl border p-4 text-left", dados.usb.papel === "device" && "border-brand bg-brand/5")}><p className="font-medium">Device</p><p className="mt-1 text-xs text-muted-foreground">{t("Ligar o dongle a um computador por USB.", "Connect the dongle to a computer over USB.")}</p></button></div></Card><Card><CardTitle hint={t(`${dados.usb.aparelhos.length} detectados`, `${dados.usb.aparelhos.length} detected`)}>{t("Aparelhos conectados", "Connected devices")}</CardTitle><RowGroup>{dados.usb.aparelhos.map(a => <Row key={a.id} icon={Usb} title={a.nome} sub={`${a.tipo} · ${a.id}`} action={<Pill tone="ok">{t("detectado", "detected")}</Pill>} />)}</RowGroup></Card></div> }

function DataPage({ slug }: { slug: string }) {
  // só as telas que não têm componente próprio (as demais são roteadas antes)
  const { dados, processar } = usePanel(); const Icon = icons[slug] ?? Settings2
  const generic: Record<string, { title: string; desc: string; body: React.ReactNode }> = {
    leds: {
      title: t("LEDs", "LEDs"),
      desc: t("Defina como as luzes do dongle se comportam.", "Set how the dongle's lights behave."),
      body: <RowGroup>{Object.entries(dados.leds).map(([id, value]) => <Row key={id} icon={Lightbulb} title={id.replace(":", " · ")} sub={t("Comportamento da luz", "Light behavior")} action={<Select defaultValue={value} onChange={(e) => processar({ mensagem: t("Ajustando " + id, "Adjusting " + id), duracao: 1500, acao: "led-set", args: { led: id, gatilho: e.target.value } })}><option value="auto">{t("Automático (OpenDongle)", "Automatic (OpenDongle)")}</option><option value="none">{t("Apagado", "Off")}</option><option value="default-on">{t("Aceso", "On")}</option><option value="heartbeat">{t("Piscando", "Blinking")}</option></Select>} />)}</RowGroup>,
    },
  }
  const page = generic[slug]
  return <div className="space-y-6"><PageHeader icon={Icon} title={page?.title ?? slug} desc={page?.desc ?? t("Configuração do OpenDongle.", "OpenDongle configuration.")}><GoBack /></PageHeader><Card>{page?.body ?? <><CardTitle>{t("Configuração", "Configuration")}</CardTitle><p className="text-sm text-muted-foreground">{t("Esta área reúne as opções avançadas do dongle.", "This area gathers the dongle's advanced options.")}</p></>}</Card></div>
}

/* ---------- telas avançadas (dados reais do motor) ---------- */

const UNIDADES_LOG: [string, [string, string]][] = [
  ["", ["Sistema inteiro", "Whole system"]],
  ["opendongle", ["OpenDongle (guarda, LEDs, descoberta)", "OpenDongle (guard, LEDs, discovery)"]],
  ["painel", ["Painel web", "Web panel"]],
  ["dnsmasq", ["DHCP e DNS (dnsmasq)", "DHCP and DNS (dnsmasq)"]],
  ["hostapd", ["Hotspot (hostapd)", "Hotspot (hostapd)"]],
  ["wifi-cliente", ["Wi-Fi cliente (wpa_supplicant)", "Wi-Fi client (wpa_supplicant)"]],
  ["rede", ["Rede (systemd-networkd)", "Network (systemd-networkd)"]],
  ["usb-4g", ["USB e 4G (usb-role-autosense)", "USB and 4G (usb-role-autosense)"]],
]

function Carregando() { return <Card><p className="text-sm text-muted-foreground">{t("Carregando…", "Loading…")}</p></Card> }
function Falhou({ erro }: { erro?: string }) { return <Card><Msg tone="err">{erro || t("Não foi possível ler os dados do dongle.", "Could not read data from the dongle.")}</Msg></Card> }

function LogsPage() {
  const [unidade, setUnidade] = useState("")
  const { dados: r, carregando, recarregar } = useApi<{ ok: boolean; texto?: string; erro?: string }>(`/api/logs?u=${encodeURIComponent(unidade)}`)
  const fim = useRef<HTMLPreElement>(null)
  // o mais recente fica embaixo: rola até lá a cada leitura
  useEffect(() => { if (fim.current) fim.current.scrollTop = fim.current.scrollHeight }, [r])
  return <div className="space-y-6"><PageHeader icon={Terminal} title={t("Logs do sistema", "System logs")} desc={t("As últimas 200 linhas do journal desde o boot.", "The last 200 journal lines since boot.")}><GoBack /></PageHeader>
    <Card>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label={t("Serviço", "Service")}><Select value={unidade} onChange={(e) => setUnidade(e.target.value)}>{UNIDADES_LOG.map(([id, [pt, en]]) => <option key={id} value={id}>{t(pt, en)}</option>)}</Select></Field>
        <Btn size="sm" variant="secondary" onClick={recarregar} disabled={carregando}><RefreshCw className={cn("size-3.5", carregando && "animate-spin")} /> {t("Atualizar", "Refresh")}</Btn>
      </div>
      {carregando && !r ? <p className="text-sm text-muted-foreground">{t("Carregando…", "Loading…")}</p>
        : !r?.ok ? <Msg tone="err">{r?.erro || t("Não foi possível ler o log.", "Could not read the log.")}</Msg>
        : <pre ref={fim} className="max-h-[28rem] overflow-auto whitespace-pre-wrap break-all rounded-lg bg-muted p-4 font-mono text-[11px] leading-5 text-muted-foreground">{r.texto?.trim() || t("(nenhuma linha)", "(no lines)")}</pre>}
    </Card>
  </div>
}

type ResultadoDiag = { nome: string; status: "ok" | "falha" | "nao_testavel"; detalhe: string; quando: number; nomeEn?: string; detalheEn?: string }

function DiagnosticoPage() {
  const { processar } = usePanel()
  const { dados: inicial, carregando } = useApi<{ ok: boolean; resultados: ResultadoDiag[] }>("/api/diagnostico")
  const [resultados, setResultados] = useState<ResultadoDiag[] | null>(null)
  const [erro, setErro] = useState("")
  const lista = resultados ?? inicial?.resultados ?? []
  const quando = lista.length ? Math.max(...lista.map((x) => x.quando)) : 0
  const tom = { ok: "ok", falha: "err", nao_testavel: "neutral" } as const
  const rotulo = { ok: t("ok", "ok"), falha: t("falhou", "failed"), nao_testavel: t("não testável", "not testable") }
  const rodar = async () => {
    setErro("")
    const res = await processar({ mensagem: t("Rodando o diagnóstico", "Running diagnostics"), detalhe: t("Áudio, Bluetooth, vídeo USB e modem — até 30 segundos.", "Audio, Bluetooth, USB video and modem — up to 30 seconds."), duracao: 20000, acao: "diagnostico-rodar" })
    if (res?.ok) setResultados((res.resultados as ResultadoDiag[]) ?? [])
    else setErro(res?.erro || t("O diagnóstico falhou.", "Diagnostics failed."))
  }
  return <div className="space-y-6"><PageHeader icon={Stethoscope} title={t("Diagnóstico de hardware", "Hardware diagnostics")} desc={t("Testa de verdade cada componente e diz o que funciona.", "Actually tests each component and reports what works.")}><GoBack /></PageHeader>
    <Card>
      <CardTitle hint={quando ? t(`última vez: ${new Date(quando * 1000).toLocaleString("pt-BR")}`, `last run: ${new Date(quando * 1000).toLocaleString("en-US")}`) : undefined}>{t("Resultados", "Results")}</CardTitle>
      {carregando && !resultados ? <p className="text-sm text-muted-foreground">{t("Carregando…", "Loading…")}</p>
        : lista.length === 0 ? <p className="text-sm text-muted-foreground">{t("Ainda não rodado desde que o dongle ligou.", "Not run yet since the dongle started.")}</p>
        : <RowGroup>{lista.map((x) => <Row key={x.nome} title={t(x.nome, x.nomeEn ?? x.nome)} sub={t(x.detalhe, x.detalheEn ?? x.detalhe)} action={<Pill tone={tom[x.status] ?? "neutral"}>{rotulo[x.status] ?? x.status}</Pill>} />)}</RowGroup>}
      <div className="mt-4 flex flex-wrap items-center gap-3"><Btn size="sm" variant="primary" onClick={rodar}><Stethoscope className="size-3.5" /> {t("Rodar diagnóstico completo", "Run full diagnostics")}</Btn>{erro ? <Msg tone="err">{erro}</Msg> : null}</div>
    </Card>
  </div>
}

type Modulo = { nome: string; kb: number; usos: number; usado_por: string[] }

function KernelPage() {
  const { dados: k, carregando } = useApi<{ ok: boolean; versao: string; build: string; arquitetura: string; cmdline: string; modulos: Modulo[]; no_boot: string[] }>("/api/kernel")
  const [filtro, setFiltro] = useState("")
  if (carregando) return <div className="space-y-6"><PageHeader icon={Server} title={t("Kernel e módulos", "Kernel and modules")}><GoBack /></PageHeader><Carregando /></div>
  if (!k?.ok) return <div className="space-y-6"><PageHeader icon={Server} title={t("Kernel e módulos", "Kernel and modules")}><GoBack /></PageHeader><Falhou /></div>
  const f = filtro.trim().toLowerCase()
  const mods = f ? k.modulos.filter((m) => m.nome.includes(f) || m.usado_por.some((u) => u.includes(f))) : k.modulos
  return <div className="space-y-6"><PageHeader icon={Server} title={t("Kernel e módulos", "Kernel and modules")} desc={t("Versão em uso, parâmetros de boot e o que está carregado.", "Running version, boot parameters and what is loaded.")}><GoBack /></PageHeader>
    <Card><CardTitle>{t("Kernel", "Kernel")}</CardTitle><RowGroup cols={2}>
      <Row title={t("Versão", "Version")} sub={`${k.versao} · ${k.arquitetura}`} />
      <Row title="Build" sub={k.build} />
    </RowGroup>
      <p className="mb-1.5 mt-4 text-xs font-medium text-muted-foreground">{t("Parâmetros de boot", "Boot parameters")}</p>
      <pre className="whitespace-pre-wrap break-all rounded-lg bg-muted p-3 font-mono text-[11px] leading-5 text-muted-foreground">{k.cmdline || "—"}</pre>
      {k.no_boot.length ? <p className="mt-3 text-xs text-muted-foreground">{t("Carregados no boot por configuração:", "Loaded at boot by configuration:")} <span className="font-mono">{k.no_boot.join(", ")}</span></p> : null}
    </Card>
    <Card><CardTitle hint={t(`${mods.length} de ${k.modulos.length}`, `${mods.length} of ${k.modulos.length}`)}>{t("Módulos carregados", "Loaded modules")}</CardTitle>
      <div className="relative mb-3 max-w-xs"><Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" /><Input value={filtro} onChange={(e) => setFiltro(e.target.value)} placeholder={t("Filtrar módulos…", "Filter modules…")} className="pl-9" /></div>
      <div className="max-h-[28rem] overflow-auto rounded-lg border border-border">
        <table className="w-full text-left text-xs"><thead className="sticky top-0 bg-card text-muted-foreground"><tr><th className="px-3 py-2 font-medium">{t("Módulo", "Module")}</th><th className="px-3 py-2 text-right font-medium">KB</th><th className="px-3 py-2 font-medium">{t("Usado por", "Used by")}</th></tr></thead>
          <tbody className="divide-y divide-border font-mono">{mods.map((m) => <tr key={m.nome}><td className="px-3 py-1.5">{m.nome}</td><td className="px-3 py-1.5 text-right tabular-nums">{m.kb}</td><td className="px-3 py-1.5 text-muted-foreground">{m.usado_por.join(", ") || "—"}</td></tr>)}</tbody>
        </table>
      </div>
    </Card>
  </div>
}

function RecursosPage() {
  const { dados: r, carregando, recarregar } = useApi<{ ok: boolean; metrica: string; ram_total_kb: number; ram_disponivel_kb: number; servicos: { unit: string; kb: number }[] }>("/api/recursos")
  const topo = <PageHeader icon={MemoryStick} title={t("Memória por serviço", "Memory per service")} desc={t("Quanto de RAM cada serviço usa agora.", "How much RAM each service is using right now.")}><GoBack /></PageHeader>
  if (carregando && !r) return <div className="space-y-6">{topo}<Carregando /></div>
  if (!r?.ok) return <div className="space-y-6">{topo}<Falhou /></div>
  const mb = (kb: number) => kb / 1024
  // abaixo de 0,5 MB é ruído (processos de passagem); a tela antiga cortava igual
  const lista = r.servicos.filter((s) => s.kb >= 512)
  const maior = Math.max(1, ...lista.map((s) => s.kb))
  const usada = r.ram_total_kb - r.ram_disponivel_kb
  return <div className="space-y-6">{topo}
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
      <Stat label={t("RAM total", "Total RAM")} value={`${mb(r.ram_total_kb).toFixed(0)} MB`} />
      <Stat label={t("Em uso", "In use")} value={`${mb(usada).toFixed(0)} MB`} />
      <Stat label={t("Disponível", "Available")} value={`${mb(r.ram_disponivel_kb).toFixed(0)} MB`} />
    </div>
    <Card><CardTitle hint={r.metrica}>{t("Serviços", "Services")}</CardTitle>
      <div className="space-y-3">{lista.map((s) => <div key={s.unit}>
        <div className="mb-1 flex items-baseline justify-between gap-3 text-sm"><span className="truncate font-mono text-xs">{s.unit}</span><span className="shrink-0 tabular-nums text-muted-foreground">{mb(s.kb).toFixed(1)} MB</span></div>
        <MiniBar value={(s.kb / maior) * 100} />
      </div>)}</div>
      <div className="mt-4"><Btn size="sm" variant="secondary" onClick={recarregar} disabled={carregando}><RefreshCw className={cn("size-3.5", carregando && "animate-spin")} /> {t("Atualizar", "Refresh")}</Btn></div>
    </Card>
  </div>
}

function ConfigArquivoPage() {
  const { dados: r, carregando } = useApi<{ ok: boolean; caminho: string; config: unknown; erro?: string }>("/api/config-arquivo")
  const topo = <PageHeader icon={FileJson} title={t("Arquivo de configuração", "Configuration file")} desc={t("De onde o dongle gera DHCP, firewall, rede, hotspot e o resto.", "Where the dongle generates DHCP, firewall, network, hotspot and the rest from.")}><GoBack /></PageHeader>
  if (carregando) return <div className="space-y-6">{topo}<Carregando /></div>
  if (!r?.ok) return <div className="space-y-6">{topo}<Falhou erro={r?.erro} /></div>
  return <div className="space-y-6">{topo}
    <Card><CardTitle hint={r.caminho}>config.json</CardTitle>
      <pre className="max-h-[32rem] overflow-auto rounded-lg bg-muted p-4 font-mono text-[11px] leading-5 text-muted-foreground">{JSON.stringify(r.config, null, 2)}</pre>
      <p className="mt-3 text-xs text-muted-foreground">{t("As senhas de Wi-Fi aparecem ocultas. Para mudar pelo terminal:", "Wi-Fi passwords are hidden. To change it from the terminal:")} <code className="font-mono">sudo opendongle config set chave=valor</code></p>
      <div className="mt-4"><a href="/api/backup" download><Btn size="sm" variant="secondary"><Download className="size-3.5" /> {t("Baixar backup completo (com senhas)", "Download full backup (with passwords)")}</Btn></a></div>
    </Card>
  </div>
}

// mesmo padrão que o motor valida (opendongle_config.RE_HOSTNAME)
const RE_HOSTNAME = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/

function NomeBackupPage() {
  const { dados, processar } = usePanel()
  const [nome, setNome] = useState(dados.hostname)
  const [msgNome, setMsgNome] = useState<{ tone: "ok" | "err"; texto: string } | null>(null)
  const [msgBackup, setMsgBackup] = useState<{ tone: "ok" | "err"; texto: string } | null>(null)
  const [confirmaReset, setConfirmaReset] = useState(false)
  const arquivo = useRef<HTMLInputElement>(null)
  useEffect(() => { setNome(dados.hostname) }, [dados.hostname])
  const nomeValido = RE_HOSTNAME.test(nome)
  const resposta = (res: ResultadoAcao | undefined, okPadrao: string) =>
    res?.ok ? { tone: "ok" as const, texto: res.aviso || okPadrao } : { tone: "err" as const, texto: res?.erro || t("Não deu certo.", "It did not work.") }

  const salvarNome = async () => {
    setMsgNome(null)
    const res = await processar({ mensagem: t("Aplicando o nome", "Applying the name"), duracao: 4000, acao: "sistema-set", args: { hostname: nome } })
    setMsgNome(resposta(res, t("Nome aplicado.", "Name applied.")))
  }
  const restaurar = async (f: File) => {
    setMsgBackup(null)
    if (f.size > 256 * 1024) { setMsgBackup({ tone: "err", texto: t("Arquivo grande demais para ser um backup do OpenDongle.", "File too large to be an OpenDongle backup.") }); return }
    const texto = await f.text()
    const res = await processar({ mensagem: t("Restaurando o backup", "Restoring the backup"), detalhe: t("A rede pode reiniciar por alguns segundos.", "The network may restart for a few seconds."), duracao: 15000, acao: "restaurar", args: { texto } })
    setMsgBackup(resposta(res, t("Backup restaurado e aplicado.", "Backup restored and applied.")))
  }
  const reset = async () => {
    setConfirmaReset(false); setMsgBackup(null)
    const res = await processar({ mensagem: t("Voltando à configuração de fábrica", "Restoring factory settings"), detalhe: t("O hotspot reinicia com o nome e a senha de fábrica.", "The hotspot restarts with the factory name and password."), duracao: 15000, acao: "reset" })
    setMsgBackup(resposta(res, t("Configuração de fábrica aplicada.", "Factory settings applied.")))
  }

  return <div className="space-y-6"><PageHeader icon={Database} title={t("Nome, backup e reset", "Name, backup and reset")} desc={t("Identidade do aparelho, cópia e restauração da configuração.", "Device identity, configuration backup and restore.")}><GoBack /></PageHeader>
    <Card><CardTitle>{t("Nome do dongle", "Dongle name")}</CardTitle>
      <Field label={t("Nome na rede", "Network name")} hint={nomeValido || !nome ? t("Letras minúsculas, números e hífen. Aparece para os outros aparelhos da rede.", "Lowercase letters, numbers and hyphen. Shown to other devices on the network.") : t("Use só letras minúsculas, números e hífen (sem começar ou terminar com hífen).", "Use only lowercase letters, numbers and hyphen (not at the start or end).")}>
        <Input value={nome} onChange={(e) => setNome(e.target.value.trim().toLowerCase())} maxLength={63} />
      </Field>
      <div className="mt-4 flex flex-wrap items-center gap-3"><Btn size="sm" variant="primary" disabled={!nomeValido || nome === dados.hostname} onClick={salvarNome}>{t("Salvar nome", "Save name")}</Btn>{msgNome ? <Msg tone={msgNome.tone}>{msgNome.texto}</Msg> : null}</div>
    </Card>
    <Card><CardTitle>{t("Backup da configuração", "Configuration backup")}</CardTitle>
      <p className="text-sm text-muted-foreground">{t("Um arquivo JSON com rede, Wi-Fi (inclusive as senhas), firewall, APNs e LEDs. Guarde em lugar seguro. Usuário e senha de administração não entram.", "A JSON file with network, Wi-Fi (passwords included), firewall, APNs and LEDs. Keep it somewhere safe. The admin username and password are not included.")}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        <a href="/api/backup" download><Btn size="sm" variant="secondary"><Download className="size-3.5" /> {t("Baixar backup", "Download backup")}</Btn></a>
        <Btn size="sm" variant="secondary" onClick={() => arquivo.current?.click()}>{t("Restaurar backup…", "Restore backup…")}</Btn>
        <input ref={arquivo} type="file" accept="application/json,.json" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) restaurar(f) }} />
      </div>
      {msgBackup ? <div className="mt-4"><Msg tone={msgBackup.tone}>{msgBackup.texto}</Msg></div> : null}
    </Card>
    <Card><CardTitle>{t("Configuração de fábrica", "Factory settings")}</CardTitle>
      <Notice>{t("Volta rede, Wi-Fi, firewall, APNs e LEDs ao padrão. O hotspot volta ao nome e à senha de fábrica — se você está conectado por ele, vai precisar reconectar. Usuário, senha de administração e foto não mudam.", "Resets network, Wi-Fi, firewall, APNs and LEDs to defaults. The hotspot goes back to the factory name and password — if you are connected through it, you will need to reconnect. The admin username, password and photo stay the same.")}</Notice>
      <div className="mt-4 flex flex-wrap gap-2">{confirmaReset
        ? <><Btn size="sm" variant="danger" onClick={reset}>{t("Sim, voltar à fábrica", "Yes, restore factory settings")}</Btn><Btn size="sm" variant="ghost" onClick={() => setConfirmaReset(false)}>{t("Cancelar", "Cancel")}</Btn></>
        : <Btn size="sm" variant="danger" onClick={() => setConfirmaReset(true)}>{t("Voltar à configuração de fábrica", "Restore factory settings")}</Btn>}</div>
    </Card>
  </div>
}

function ServicosPage() {
  // a lista vem sob demanda: é a leitura mais cara do dongle (systemctl)
  const { processar } = usePanel()
  const { dados: r, carregando, recarregar } = useApi<{ ok: boolean; servicos: Servico[] }>("/api/servicos")
  const [erro, setErro] = useState("")
  const mudar = async (s: Servico, v: boolean) => {
    setErro("")
    const res = await processar({ mensagem: t((v ? "Ligando " : "Desligando ") + s.nome, (v ? "Starting " : "Stopping ") + s.nome), duracao: 4000, acao: "servico-set", args: { nome: s.nome, ligar: v } })
    if (res && !res.ok) setErro(res.erro || t("Não mudou.", "It did not change."))
    recarregar()
  }
  return <div className="space-y-6"><PageHeader icon={Server} title={t("Serviços do sistema", "System services")} desc={t("O que sobe no boot: ligar e desligar.", "What starts at boot: on and off.")}><GoBack /></PageHeader>
    {erro ? <Msg tone="err">{erro}</Msg> : null}
    <Card>{carregando && !r ? <p className="text-sm text-muted-foreground">{t("Carregando…", "Loading…")}</p> : !r?.ok ? <Msg tone="err">{t("Não foi possível ler os serviços.", "Could not read the services.")}</Msg> : <RowGroup>{r.servicos.map(s => <Row key={s.nome} icon={Server} title={s.nome} sub={t(`${s.ramMb.toFixed(1)} MB · ${s.rodando ? "rodando" : "parado"}`, `${s.ramMb.toFixed(1)} MB · ${s.rodando ? "running" : "stopped"}`)} action={s.essencial ? <Pill tone="neutral">{t("essencial", "essential")}</Pill> : <Toggle checked={s.habilitado} label="" onChange={(v) => mudar(s, v)} />} />)}</RowGroup>}</Card>
  </div>
}

function AdvancedLeaf({ slug }: { slug: string }) {
  if (slug === "servicos") return <ServicosPage />
  if (slug === "logs") return <LogsPage />
  if (slug === "diagnostico") return <DiagnosticoPage />
  if (slug === "kernel") return <KernelPage />
  if (slug === "recursos") return <RecursosPage />
  return <ConfigArquivoPage />
}

function BluetoothPage() {
  const { dados, processar } = usePanel(); const bt = dados.bluetooth
  const acao = (mensagem: string, a: string, args: Record<string, unknown>, duracao = 6000) =>
    () => processar({ mensagem, duracao, acao: a, args })
  return <div className="space-y-6"><PageHeader icon={Bluetooth} title="Bluetooth" desc={t("Pareie e gerencie fones, caixas, teclados e controles.", "Pair and manage headsets, speakers, keyboards and controllers.")}><GoBack /></PageHeader>
    <Card><div className="flex flex-wrap items-center justify-between gap-3"><div><CardTitle hint={bt.ligado ? t("ligado", "on") : t("desligado", "off")}>{t("Rádio Bluetooth", "Bluetooth radio")}</CardTitle><p className="text-sm text-muted-foreground">{bt.nome} · {bt.mac}</p></div><Toggle checked={bt.ligado} label={t("Bluetooth ligado", "Bluetooth on")} onChange={(v) => processar({ mensagem: v ? t("Ligando o Bluetooth", "Turning Bluetooth on") : t("Desligando o Bluetooth", "Turning Bluetooth off"), duracao: 4000, acao: "bt-ligar", args: { ligar: v } })} /></div></Card>
    {bt.ligado && <><Card><CardTitle hint={t(`${bt.pareados.length} aparelhos`, `${bt.pareados.length} devices`)}>{t("Aparelhos pareados", "Paired devices")}</CardTitle>{bt.pareados.length ? <RowGroup>{bt.pareados.map(d => <Row key={d.mac} icon={Bluetooth} title={d.nome} sub={`${d.tipo || t("aparelho", "device")} · ${d.mac}${d.bateria != null ? " · " + d.bateria + "%" : ""}`} action={<div className="flex items-center gap-2">{d.conectado ? <Btn size="sm" variant="secondary" onClick={acao(t("Desconectando " + d.nome, "Disconnecting " + d.nome), "bt-desconectar", { mac: d.mac }, 5000)}>{t("Desconectar", "Disconnect")}</Btn> : <Btn size="sm" variant="primary" onClick={acao(t("Conectando " + d.nome, "Connecting " + d.nome), "bt-conectar", { mac: d.mac }, 12000)}>{t("Conectar", "Connect")}</Btn>}<Btn size="sm" variant="ghost" onClick={acao(t("Esquecendo " + d.nome, "Forgetting " + d.nome), "bt-esquecer", { mac: d.mac }, 4000)}>{t("Esquecer", "Forget")}</Btn></div>} />)}</RowGroup> : <p className="text-sm text-muted-foreground">{t("Nenhum aparelho pareado ainda.", "No paired devices yet.")}</p>}<div className="mt-4 flex gap-2"><Btn size="sm" onClick={() => processar({ mensagem: t("Procurando aparelhos Bluetooth", "Scanning for Bluetooth devices"), duracao: 12000, acao: "bt-buscar" })}><Search className="size-3.5" /> {t("Procurar aparelhos", "Scan for devices")}</Btn><Btn size="sm" variant="secondary" onClick={() => processar({ mensagem: t("Deixando o dongle visível", "Making the dongle discoverable"), duracao: 2000, acao: "bt-visivel", args: { visivel: true } })}>{t("Tornar visível", "Make discoverable")}</Btn></div></Card>
    {bt.novos.length > 0 && <Card><CardTitle hint={t(`${bt.novos.length} encontrados`, `${bt.novos.length} found`)}>{t("Aparelhos encontrados", "Devices found")}</CardTitle><RowGroup>{bt.novos.map(d => <Row key={d.mac} icon={Bluetooth} title={d.nome} sub={`${d.tipo || t("aparelho", "device")} · ${d.mac}`} action={<Btn size="sm" variant="primary" onClick={acao(t("Pareando " + d.nome, "Pairing " + d.nome), "bt-parear", { mac: d.mac }, 20000)}>{t("Parear", "Pair")}</Btn>} />)}</RowGroup></Card>}</>}
  </div>
}

function VolumeLinha({ label, sub, volume, mudo, onVol, onMudo, onTestar }: { label: string; sub?: string; volume: number; mudo: boolean; onVol: (v: number) => void; onMudo: (v: boolean) => void; onTestar?: () => void }) {
  return <div className="border-b border-border py-3 last:border-b-0"><div className="flex items-center justify-between gap-3"><div className="min-w-0"><p className="truncate text-sm font-medium">{label}</p>{sub && <p className="truncate text-xs text-muted-foreground">{sub}</p>}</div><div className="flex items-center gap-2">{onTestar && <Btn size="sm" variant="secondary" onClick={onTestar}>{t("Tocar teste", "Play test")}</Btn>}<Toggle checked={!mudo} label="" onChange={(v) => onMudo(!v)} /></div></div><input type="range" min={0} max={100} defaultValue={volume} className="mt-2 w-full accent-brand" onPointerUp={(e) => onVol(Number((e.target as HTMLInputElement).value))} onKeyUp={(e) => onVol(Number((e.target as HTMLInputElement).value))} /></div>
}

function AudioPage() {
  const { dados, processar } = usePanel(); const a = dados.audio
  return <div className="space-y-6"><PageHeader icon={Volume2} title={t("Áudio", "Audio")} desc={t("Placas de som USB, fones Bluetooth, volume e microfone.", "USB sound cards, Bluetooth headsets, volume and microphone.")}><GoBack /></PageHeader>
    <Card><div className="flex items-center justify-between gap-3"><div><CardTitle hint={a.bluetoothLigado ? t("ligado", "on") : t("desligado", "off")}>{t("Áudio por Bluetooth", "Bluetooth audio")}</CardTitle><p className="text-sm text-muted-foreground">{t("Liga o PipeWire para tocar em fones e caixas.", "Starts PipeWire to play on headsets and speakers.")}</p></div><Toggle checked={a.bluetoothLigado} label={t("Áudio Bluetooth", "Bluetooth audio")} onChange={(v) => processar({ mensagem: v ? t("Preparando o áudio Bluetooth", "Preparing Bluetooth audio") : t("Desligando o áudio Bluetooth", "Turning off Bluetooth audio"), duracao: 15000, acao: "audio-bt-set", args: { ligar: v } })} /></div></Card>
    {a.placas.length ? a.placas.map(pl => <Card key={pl.id}><div className="flex items-center justify-between gap-3"><CardTitle hint={pl.padrao ? t("padrão", "default") : undefined}>{pl.nome}</CardTitle>{!pl.padrao && <Btn size="sm" variant="secondary" onClick={() => processar({ mensagem: t("Definindo placa padrão", "Setting default sound card"), duracao: 2000, acao: "audio-padrao", args: { placa: pl.id } })}>{t("Usar como padrão", "Use as default")}</Btn>}</div>{pl.controles.map(c => <VolumeLinha key={c.nome} label={c.nome} sub={c.tipo} volume={c.volume} mudo={c.mudo} onVol={(v) => processar({ mensagem: t("Ajustando volume", "Adjusting volume"), duracao: 800, acao: "audio-ajustar", args: { placa: pl.id, controle: c.nome, volume: v } })} onMudo={(m) => processar({ mensagem: m ? t("Mudo", "Mute") : t("Ativando som", "Unmuting"), duracao: 800, acao: "audio-ajustar", args: { placa: pl.id, controle: c.nome, mudo: m } })} onTestar={c.tipo === "saída" ? () => processar({ mensagem: t("Tocando som de teste", "Playing test sound"), duracao: 3000, acao: "audio-testar", args: { placa: pl.id } }) : undefined} />)}</Card>) : <Card><p className="text-sm text-muted-foreground">{t("Nenhuma placa de som USB detectada. Plugue uma placa na porta USB (modo host).", "No USB sound card detected. Plug one into the USB port (host mode).")}</p></Card>}
    {a.bluetoothLigado && (a.btSaidas.length > 0 || a.btEntradas.length > 0) && <Card><CardTitle>{t("Fones e caixas Bluetooth", "Bluetooth headsets and speakers")}</CardTitle>{a.btSaidas.map(s => <div key={s.id}><VolumeLinha label={s.nome} sub={t("saída", "output")} volume={s.volume} mudo={s.mudo} onVol={(v) => processar({ mensagem: t("Ajustando volume", "Adjusting volume"), duracao: 800, acao: "audio-bt-ajustar", args: { no: s.id, volume: v } })} onMudo={(m) => processar({ mensagem: m ? t("Mudo", "Mute") : t("Ativando som", "Unmuting"), duracao: 800, acao: "audio-bt-ajustar", args: { no: s.id, mudo: m } })} />{a.btModos[String(s.id)] && <div className="pb-3"><Segmented value={a.btModos[String(s.id)]} options={[{ value: "musica", label: t("Música", "Music") }, { value: "chamada", label: t("Chamada (com microfone)", "Call (with microphone)") }]} onChange={(m) => processar({ mensagem: t("Trocando o modo do áudio", "Switching audio mode"), duracao: 4000, acao: "audio-bt-modo", args: { dev: s.dev ?? s.id, modo: m } })} /></div>}</div>)}{a.btEntradas.map(e => <VolumeLinha key={e.id} label={e.nome} sub={t("microfone", "microphone")} volume={e.volume} mudo={e.mudo} onVol={(v) => processar({ mensagem: t("Ajustando microfone", "Adjusting microphone"), duracao: 800, acao: "audio-bt-ajustar", args: { no: e.id, volume: v } })} onMudo={(m) => processar({ mensagem: m ? t("Mudo", "Mute") : t("Ativando microfone", "Unmuting microphone"), duracao: 800, acao: "audio-bt-ajustar", args: { no: e.id, mudo: m } })} />)}</Card>}
  </div>
}

function TorPage() {
  const { dados, processar } = usePanel(); const on = dados.tor.ativo
  return <div className="space-y-6"><PageHeader icon={ShieldCheck} title={t("Navegação via Tor", "Browsing via Tor")} desc={t("Faz todo o tráfego dos aparelhos da rede passar pela rede Tor.", "Routes all network devices' traffic through the Tor network.")}><GoBack /></PageHeader><Card><div className="flex items-center justify-between gap-3"><div><CardTitle hint={on ? t("ligado", "on") : t("desligado", "off")}>{t("Rede Tor", "Tor network")}</CardTitle><p className="text-sm text-muted-foreground">{t("Mais privacidade, porém mais lento. Alguns sites podem bloquear.", "More privacy, but slower. Some sites may block it.")}</p></div><Toggle checked={on} label="Tor" onChange={(v) => processar({ mensagem: v ? t("Ligando o Tor (pode baixar o pacote)", "Turning Tor on (may download the package)") : t("Desligando o Tor", "Turning Tor off"), duracao: 20000, acao: "tor-set", args: { ligar: v } })} /></div></Card></div>
}

function RemotoPage() {
  const { dados, processar } = usePanel(); const r = dados.remoto
  return <div className="space-y-6"><PageHeader icon={Network} title={t("Acesso remoto", "Remote access")} desc={t("Acesse o dongle de longe, de qualquer lugar, via Tailscale.", "Reach the dongle from anywhere, via Tailscale.")}><GoBack /></PageHeader><Card><div className="flex items-center justify-between gap-3"><div><CardTitle hint={r.ativo ? t("ligado", "on") : t("desligado", "off")}>Tailscale</CardTitle><p className="text-sm text-muted-foreground">{t("Cria um endereço privado para chegar ao painel de fora da rede.", "Creates a private address to reach the panel from outside the network.")}</p></div><Toggle checked={r.ativo} label={t("Acesso remoto", "Remote access")} onChange={(v) => processar({ mensagem: v ? t("Ligando o acesso remoto (pode baixar o pacote)", "Turning remote access on (may download the package)") : t("Desligando o acesso remoto", "Turning remote access off"), duracao: 20000, acao: "remoto-set", args: { ligar: v, lan: r.lan, saida: r.saida } })} /></div>{r.ativo && <div className="mt-4 space-y-3 border-t border-border pt-4"><Toggle checked={r.lan} label={t("Compartilhar a rede local com meus outros aparelhos", "Share the local network with my other devices")} onChange={(v) => processar({ mensagem: t("Aplicando", "Applying"), duracao: 4000, acao: "remoto-set", args: { ligar: true, lan: v, saida: r.saida } })} /><Toggle checked={r.saida} label={t("Usar o dongle como saída de internet (exit node)", "Use the dongle as an internet exit node")} onChange={(v) => processar({ mensagem: t("Aplicando", "Applying"), duracao: 4000, acao: "remoto-set", args: { ligar: true, lan: r.lan, saida: v } })} /></div>}</Card></div>
}

function FirewallPage() {
  const { dados, processar } = usePanel(); const fw = dados.firewall
  const [nome, setNome] = useState(""); const [proto, setProto] = useState("tcp"); const [pe, setPe] = useState(""); const [ip, setIp] = useState(""); const [pi, setPi] = useState("")
  const setFlag = (campo: string, v: boolean) => processar({ mensagem: t("Aplicando firewall", "Applying firewall"), duracao: 4000, acao: "fw-set", args: { wifiClienteConfiavel: fw.wifiClienteConfiavel, sshPelaWan: fw.sshPelaWan, painelPelaWan: fw.painelPelaWan, [campo]: v } })
  const adicionar = async () => { await processar({ mensagem: t("Adicionando redirecionamento", "Adding port forward"), duracao: 4000, acao: "redir-add", args: { nome, proto, portaExterna: Number(pe), ip, portaInterna: Number(pi) } }); setNome(""); setPe(""); setIp(""); setPi("") }
  return <div className="space-y-6"><PageHeader icon={LockKeyhole} title={t("Firewall e portas", "Firewall and ports")} desc={t("A rede local sempre tem acesso; o 4G fica fechado exceto o que você liberar.", "The local network always has access; 4G stays closed except what you open.")}><GoBack /></PageHeader>
    <Card><CardTitle>{t("Acesso pela internet (4G)", "Access from the internet (4G)")}</CardTitle><div className="space-y-3"><Toggle checked={fw.wifiClienteConfiavel} label={t("Confiar na rede Wi-Fi de casa (acesso liberado por ela)", "Trust the home Wi-Fi network (access allowed through it)")} onChange={(v) => setFlag("wifiClienteConfiavel", v)} /><Toggle checked={fw.sshPelaWan} label={t("Liberar SSH pela internet (porta 22)", "Allow SSH from the internet (port 22)")} onChange={(v) => setFlag("sshPelaWan", v)} /><Toggle checked={fw.painelPelaWan} label={t("Liberar o painel pela internet (porta 80)", "Allow the panel from the internet (port 80)")} onChange={(v) => setFlag("painelPelaWan", v)} /></div></Card>
    <Card><CardTitle hint={`${fw.redirecionamentos.length}`}>{t("Redirecionamento de portas", "Port forwarding")}</CardTitle>{fw.redirecionamentos.length ? <RowGroup>{fw.redirecionamentos.map(x => <Row key={x.nome} icon={Network} title={x.nome} sub={`${x.proto} ${x.portaExterna} → ${x.ip}:${x.portaInterna}`} action={<Btn size="sm" variant="ghost" onClick={() => processar({ mensagem: t("Removendo", "Removing"), duracao: 3000, acao: "redir-rm", args: { nome: x.nome } })}>{t("Remover", "Remove")}</Btn>} />)}</RowGroup> : <p className="text-sm text-muted-foreground">{t("Nenhum redirecionamento.", "No port forwards.")}</p>}<div className="mt-4 grid gap-2 sm:grid-cols-2"><Field label={t("Nome", "Name")}><Input value={nome} onChange={e => setNome(e.target.value)} /></Field><Field label={t("Protocolo", "Protocol")}><Select value={proto} onChange={e => setProto(e.target.value)}><option value="tcp">tcp</option><option value="udp">udp</option></Select></Field><Field label={t("Porta externa", "External port")}><Input value={pe} onChange={e => setPe(e.target.value)} /></Field><Field label={t("IP interno", "Internal IP")}><Input value={ip} onChange={e => setIp(e.target.value)} placeholder="192.168.100.x" /></Field><Field label={t("Porta interna", "Internal port")}><Input value={pi} onChange={e => setPi(e.target.value)} /></Field></div><Btn variant="primary" className="mt-3" onClick={adicionar} disabled={!nome || !pe || !ip || !pi}>{t("Adicionar redirecionamento", "Add port forward")}</Btn></Card></div>
}

function HoraPage() {
  const { dados, processar } = usePanel(); const h = dados.hora
  const [fuso, setFuso] = useState(h.fuso); const [auto, setAuto] = useState(h.automatica)
  const FUSOS = ["America/Sao_Paulo", "America/Manaus", "America/Belem", "America/Fortaleza", "America/Cuiaba", "America/Rio_Branco", "America/Noronha", "UTC"]
  return <div className="space-y-6"><PageHeader icon={Clock3} title={t("Data e hora", "Date and time")} desc={t("Relógio, fuso horário e sincronização automática.", "Clock, time zone and automatic synchronization.")}><GoBack /></PageHeader><Card>{h.agora && <p className="mb-4 text-sm text-muted-foreground">{t("Agora no dongle:", "Now on the dongle:")} <span className="font-medium text-foreground">{h.agora}</span></p>}<div className="max-w-xl space-y-4"><Field label={t("Fuso horário", "Time zone")}><Select value={fuso} onChange={e => setFuso(e.target.value)}>{FUSOS.map(f => <option key={f} value={f}>{f}</option>)}</Select></Field><Toggle checked={auto} label={t("Acertar o relógio automaticamente pela internet", "Set the clock automatically over the internet")} onChange={setAuto} /><Btn variant="primary" onClick={() => processar({ mensagem: t("Salvando data e hora", "Saving date and time"), duracao: 3000, acao: "hora-set", args: { automatica: auto, fuso } })}>{t("Salvar horário", "Save time")}</Btn></div></Card></div>
}

function AtualizacoesPage() {
  const { processar } = usePanel()
  return <div className="space-y-6"><PageHeader icon={Download} title={t("Atualizações", "Updates")} desc={t("Correções e melhorias do sistema.", "System fixes and improvements.")}><GoBack /></PageHeader><Card><CardTitle>{t("Sistema", "System")}</CardTitle><p className="text-sm text-muted-foreground">{t("Verifique e instale atualizações do Debian. Precisa de internet.", "Check and install Debian updates. Requires internet.")}</p><div className="mt-4 flex gap-2"><Btn variant="secondary" onClick={() => processar({ mensagem: t("Procurando atualizações", "Checking for updates"), duracao: 25000, acao: "atualizacoes", args: { instalar: false } })}><RefreshCw className="size-4" /> {t("Verificar", "Check")}</Btn><Btn variant="primary" onClick={() => processar({ mensagem: t("Instalando atualizações", "Installing updates"), duracao: 120000, acao: "atualizacoes", args: { instalar: true } })}><Download className="size-4" /> {t("Instalar", "Install")}</Btn></div></Card></div>
}

function useApi<T>(rota: string, intervalo = 0) {
  const [dados, setDados] = useState<T | null>(null)
  const [carregando, setCarregando] = useState(true)
  const [versao, setVersao] = useState(0)
  useEffect(() => {
    let vivo = true
    setCarregando(true)
    const puxar = async () => { const d = await apiGet<T>(rota); if (vivo) { setDados(d); setCarregando(false) } }
    puxar()
    if (intervalo) {
      const id = setInterval(() => { if (!document.hidden) puxar() }, intervalo)
      return () => { vivo = false; clearInterval(id) }
    }
    return () => { vivo = false }
  }, [rota, intervalo, versao])
  return { dados, carregando, recarregar: () => setVersao((v) => v + 1) }
}

function StatusPage() {
  const { dados } = useApi<{ saude: any; estado: any }>("/api/status", 5000)
  const sa = dados?.saude, st = dados?.estado
  const ramPct = sa?.ram ? Math.round(100 - sa.ram.disponivel_kb * 100 / (sa.ram.total_kb || 1)) : 0
  return <div className="space-y-6"><PageHeader icon={Activity} title={t("Status e saúde", "Status and health")} desc={t("Como está o dongle agora.", "How the dongle is doing right now.")}><GoBack /></PageHeader>
    {!dados ? <Card><p className="text-sm text-muted-foreground">{t("Carregando…", "Loading…")}</p></Card> : <>
    <Card><div className="flex flex-wrap items-center gap-3"><Pill tone={st?.internet ? "ok" : "warn"}>{st?.internet ? t("conectado à internet", "connected to the internet") : t("sem internet", "no internet")}</Pill><span className="text-sm text-muted-foreground">{st?.modo === "wifi" ? `Wi-Fi · ${st?.endereco?.ssid ?? ""}` : st?.modo === "hotspot" ? `Hotspot · ${st?.ssidHotspot ?? ""}` : "—"}</span></div>{st?.endereco && <p className="mt-3 text-sm">{t("Endereço nesta rede:", "Address on this network:")} <b>{st.endereco.ip}</b>{!st.endereco.agora && t(" (último visto)", " (last seen)")}</p>}</Card>
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <Stat label={t("CPU (1 min)", "CPU (1 min)")} value={sa?.cpu ? `${sa.cpu.carga_1m?.toFixed?.(2) ?? sa.cpu.carga_1m}` : "—"} />
      <Stat label={t("RAM usada", "RAM used")} value={`${ramPct}%`} tone={ramPct > 85 ? "err" : ramPct > 70 ? "warn" : ""} bar={ramPct} />
      <Stat label={t("Disco", "Disk")} value={`${sa?.disco_raiz?.usado_pct ?? 0}%`} bar={sa?.disco_raiz?.usado_pct ?? 0} />
      <Stat label={t("Temperatura", "Temperature")} value={sa?.temp_cpu_c != null ? `${Math.round(sa.temp_cpu_c)}°` : "—"} tone={sa?.temp_cpu_c > 70 ? "err" : sa?.temp_cpu_c > 60 ? "warn" : ""} />
    </div>
    <Card><CardTitle>{t("Detalhes", "Details")}</CardTitle><RowGroup cols={2}>
      <Row title={t("Memória", "Memory")} sub={sa?.ram ? t(`${Math.round(sa.ram.disponivel_kb/1024)} MB livres de ${Math.round(sa.ram.total_kb/1024)} MB`, `${Math.round(sa.ram.disponivel_kb/1024)} MB free of ${Math.round(sa.ram.total_kb/1024)} MB`) : "—"} />
      <Row title={t("Disco raiz", "Root disk")} sub={sa?.disco_raiz ? t(`${sa.disco_raiz.usado_gb} GB de ${sa.disco_raiz.total_gb} GB`, `${sa.disco_raiz.usado_gb} GB of ${sa.disco_raiz.total_gb} GB`) : "—"} />
      <Row title={t("Ligado há", "Up for")} sub={sa?.uptime_s != null ? `${Math.floor(sa.uptime_s/3600)}h ${Math.floor(sa.uptime_s%3600/60)}min` : "—"} />
      <Row title={t("Núcleos", "Cores")} sub={sa?.cpu?.nucleos ?? "—"} />
    </RowGroup>{sa?.temperaturas_c && <div className="mt-3 text-xs text-muted-foreground">{Object.entries(sa.temperaturas_c).map(([k,v]) => `${k}: ${v}°`).join(" · ")}</div>}</Card>
    <RebootCard />
    </>}
  </div>
}

function DesempenhoPage() {
  const { dados } = useApi<any>("/api/desempenho", 2500)
  const { processar } = usePanel()
  if (!dados?.ok) return <div className="space-y-6"><PageHeader icon={Cpu} title={t("Desempenho", "Performance")} desc={t("CPU, memória e processos ao vivo.", "Live CPU, memory and processes.")}><GoBack /></PageHeader><Card><p className="text-sm text-muted-foreground">{dados ? t("Não foi possível ler o desempenho.", "Could not read performance data.") : t("Carregando…", "Loading…")}</p></Card></div>
  return <div className="space-y-6"><PageHeader icon={Cpu} title={t("Desempenho", "Performance")} desc={t("CPU, memória e processos — atualiza sozinho.", "CPU, memory and processes — refreshes on its own.")}><GoBack /></PageHeader>
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <Stat label={t("Carga (1 min)", "Load (1 min)")} value={`${dados.carga?.[0] ?? "—"}`} />
      <Stat label={t("RAM livre", "RAM free")} value={`${dados.ram?.disponivel_mb ?? "—"} MB`} bar={dados.ram ? Math.round(100 - dados.ram.disponivel_mb*100/(dados.ram.total_mb||1)) : 0} />
      <Stat label={t("Swap (zram)", "Swap (zram)")} value={`${dados.swap?.usado_mb ?? 0} MB`} />
      <Stat label={t("Núcleos", "Cores")} value={`${dados.nucleos ?? "—"}`} />
    </div>
    <Card><CardTitle>{t("Processos que mais usam", "Top processes")}</CardTitle><RowGroup>{(dados.processos || []).slice(0,8).map((p: any) => <Row key={p.pid} title={p.nome} sub={`PID ${p.pid} · CPU ${p.cpu}% · ${p.ram_mb} MB`} action={p.protegido ? <Pill tone="neutral">{t("protegido", "protected")}</Pill> : <Btn size="sm" variant="ghost" onClick={() => processar({ mensagem: t("Encerrando " + p.nome, "Stopping " + p.nome), duracao: 2000, acao: "processo-encerrar", args: { pid: p.pid } })}>{t("Encerrar", "Stop")}</Btn>} />)}</RowGroup></Card>
  </div>
}

function EspacoPage() {
  const { dados, carregando } = useApi<any>("/api/espaco")
  const { processar } = usePanel()
  const lib = dados?.liberavel
  const totalLib = lib ? (lib.cache_apt_mb + lib.logs_antigos_mb + lib.journal_mb) : 0
  return <div className="space-y-6"><PageHeader icon={HardDrive} title={t("Espaço em disco", "Disk space")} desc={t("O que ocupa o armazenamento e como liberar.", "What fills the storage and how to free it.")}><GoBack /></PageHeader>
    {carregando ? <Card><p className="text-sm text-muted-foreground">{t("Carregando…", "Loading…")}</p></Card> : <>
    <Card><CardTitle>{t("Discos", "Disks")}</CardTitle><RowGroup>{(dados?.discos || []).map((d: any) => <Row key={d.ponto} title={d.nome} sub={`${d.ponto} · ${Math.round((d.total_mb-d.livre_mb)/1024*10)/10} GB de ${Math.round(d.total_mb/1024*10)/10} GB`} action={<div className="w-28"><MiniBar value={d.usado_pct} tone={d.usado_pct > 90 ? "err" : d.usado_pct > 75 ? "warn" : "ok"} /></div>} />)}</RowGroup></Card>
    <Card><CardTitle hint={`${totalLib} MB`}>{t("Liberar espaço", "Free space")}</CardTitle><p className="text-sm text-muted-foreground">{t("Cache do APT:", "APT cache:")} {lib?.cache_apt_mb ?? 0} MB · {t("logs antigos:", "old logs:")} {lib?.logs_antigos_mb ?? 0} MB · journal: {lib?.journal_mb ?? 0} MB</p><div className="mt-4 flex gap-2"><Btn size="sm" variant="secondary" onClick={() => processar({ mensagem: t("Analisando o disco", "Analyzing the disk"), duracao: 8000, acao: "espaco-analisar" })}>{t("Analisar", "Analyze")}</Btn><Btn size="sm" variant="primary" disabled={!totalLib} onClick={() => processar({ mensagem: t("Liberando espaço", "Freeing space"), duracao: 10000, acao: "espaco-liberar" })}>{t(`Liberar ${totalLib} MB`, `Free ${totalLib} MB`)}</Btn></div></Card>
    </>}
  </div>
}

function HardwarePage() {
  const { dados, carregando } = useApi<any>("/api/hardware")
  const h = dados
  return <div className="space-y-6"><PageHeader icon={Router} title={t("Hardware", "Hardware")} desc={t("Identificação real dos componentes do dongle.", "Real identification of the dongle's components.")}><GoBack /></PageHeader>
    {carregando ? <Card><p className="text-sm text-muted-foreground">{t("Carregando…", "Loading…")}</p></Card> : !h?.ok ? <Card><p className="text-sm text-muted-foreground">{t("Não foi possível ler o hardware.", "Could not read the hardware.")}</p></Card> : <>
    <Card><CardTitle>{h.placa}{h.compativel === false && t(" (não homologada)", " (not validated)")}</CardTitle><RowGroup cols={2}>
      <Row icon={Cpu} title={t("Processador", "Processor")} sub={`${h.soc} · ${h.cpu}`} />
      <Row icon={Cpu} title={t("Núcleos", "Cores")} sub={`${h.nucleos} × ${h.mhz} MHz · ${h.governor}`} />
      <Row icon={MemoryStick} title={t("Memória", "Memory")} sub={`${h.ram_mb} MB`} />
      <Row icon={HardDrive} title="eMMC" sub={h.emmc ? t(`${h.emmc.modelo} · ${h.emmc.tamanho_gb} GB · desgaste ${h.emmc.desgaste}`, `${h.emmc.modelo} · ${h.emmc.tamanho_gb} GB · wear ${h.emmc.desgaste}`) : "—"} />
      <Row icon={Wifi} title="Wi-Fi" sub={h.wifi ? `${h.wifi.driver} · ${h.wifi.mac}` : "—"} />
      <Row icon={Bluetooth} title="Bluetooth" sub={h.bluetooth_mac || "—"} />
      <Row icon={Radio} title={t("Modem 4G", "4G modem")} sub={h.modem ? `${h.modem.firmware || ""} ${h.modem.imei ? "· IMEI " + h.modem.imei : ""}` : "—"} />
      <Row icon={Usb} title="MAC USB" sub={h.usb_mac || "—"} />
    </RowGroup></Card>
    <Card><CardTitle>{t("Sistema", "System")}</CardTitle><RowGroup cols={2}>
      <Row title="Kernel" sub={h.kernel} />
      <Row title={t("Sistema", "System")} sub={h.sistema} />
      <Row title={t("Ligado há", "Up for")} sub={h.ligado_ha} />
    </RowGroup></Card>
    </>}
  </div>
}

function RebootCard() {
  const [fase, setFase] = useState<"" | "reiniciando" | "desligando">("")
  const energia = async (acao: "reboot" | "poweroff") => {
    const txt = acao === "reboot" ? "reiniciando" : "desligando"
    if (!confirm(acao === "reboot" ? t("Reiniciar o dongle agora?", "Reboot the dongle now?") : t("Desligar o dongle? Para ligar de novo, tire e recoloque na tomada.", "Power off the dongle? To turn it on again, unplug and plug it back in."))) return
    setFase(txt)
    try { await fetch("/api/acao", { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify({ acao: "energia", args: { acao } }) }) } catch {}
    if (acao === "reboot") {
      // espera o dongle voltar e recarrega sozinho — sem página de erro
      const t0 = Date.now()
      const tenta = async () => {
        if (Date.now() - t0 > 180000) { window.location.href = "/"; return }
        try { const r = await fetch("/api/contexto", { cache: "no-store" }); if (r.ok) { window.location.href = "/"; return } } catch {}
        setTimeout(tenta, 3000)
      }
      setTimeout(tenta, 15000)
    }
  }
  return <><Card><CardTitle>{t("Energia", "Power")}</CardTitle><div className="flex gap-2"><Btn size="sm" variant="secondary" onClick={() => energia("reboot")}><RefreshCw className="size-4" /> {t("Reiniciar", "Reboot")}</Btn><Btn size="sm" variant="danger" onClick={() => energia("poweroff")}><Zap className="size-4" /> {t("Desligar", "Power off")}</Btn></div></Card>
    {fase && <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/95 px-6 text-center"><div className="max-w-sm space-y-4"><RefreshCw className="mx-auto size-8 animate-spin text-brand" /><h2 className="text-lg font-semibold">{fase === "reiniciando" ? t("Reiniciando o dongle…", "Rebooting the dongle…") : t("Desligando o dongle…", "Powering off the dongle…")}</h2><p className="text-sm text-muted-foreground">{fase === "reiniciando" ? t("Isso leva cerca de 40 segundos. Esta página volta sozinha quando o dongle estiver pronto — não feche.", "This takes about 40 seconds. This page comes back on its own when the dongle is ready — don't close it.") : t("Pode tirar da tomada quando as luzes apagarem. Para ligar de novo, recoloque na tomada.", "You can unplug it once the lights go out. To turn it on again, plug it back in.")}</p></div></div>}
  </>
}

export function SlugView({ slug }: { slug: string }) {
  if (slug in groups) return <ListPage group={slug as keyof typeof groups} />
  if (slug === "perfil") return <Perfil />
  if (slug === "senha") return <Perfil password />
  if (slug === "bluetooth") return <BluetoothPage />
  if (slug === "usb") return <UsbPage />
  if (slug === "audio") return <AudioPage />
  if (slug === "tor") return <TorPage />
  if (slug === "remoto") return <RemotoPage />
  if (slug === "firewall") return <FirewallPage />
  if (slug === "hora") return <HoraPage />
  if (slug === "atualizacoes") return <AtualizacoesPage />
  if (slug === "status") return <StatusPage />
  if (slug === "desempenho") return <DesempenhoPage />
  if (slug === "espaco") return <EspacoPage />
  if (slug === "hardware") return <HardwarePage />
  if (slug === "nome-backup") return <NomeBackupPage />
  if (["logs", "diagnostico", "kernel", "recursos", "servicos", "config-arquivo"].includes(slug)) return <AdvancedLeaf slug={slug} />
  return <DataPage slug={slug || "sistema"} />
}
