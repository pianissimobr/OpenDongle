"use client"

import Link from "next/link"
import { useState, useEffect } from "react"
import {
  Activity, AudioLines, CalendarClock, Check, CircleHelp, Cpu, Database,
  FileJson, HardDrive, KeyRound, Lightbulb, ListTree, LockKeyhole,
  MemoryStick, Network, RefreshCw, Router, Search, Server, Settings2,
  ShieldCheck, Stethoscope, Terminal, Thermometer, UserRound, Wifi,
  Wrench, Zap, Bluetooth, Usb, Volume2, Radio, Clock3, Download,
} from "lucide-react"
import { Card, CardTitle, Field, Input, Select, Textarea, Btn, Notice, Pill, Row, RowGroup, Stat, MiniBar, Toggle, Segmented, PageHeader } from "@/components/panel/ui"
import { usePanel, PERFIL, apiGet } from "@/lib/panel/store"
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
  perfil: { title: "Perfil", desc: "Sua conta, senha e foto de administrador.", items: [["/perfil", "Conta e identidade", "Nome, usuário e foto do administrador"], ["/senha", "Senha de acesso", "Trocar a senha e encerrar outras sessões"]] },
  dispositivos: { title: "Dispositivos", desc: "Bluetooth, USB, áudio e luzes do aparelho.", items: [["/bluetooth", "Bluetooth", "Parear fones, caixas e outros aparelhos"], ["/usb", "Aparelhos USB", "Escolher o papel da porta e ver aparelhos conectados"], ["/audio", "Áudio", "Placas, volume, microfone e saídas Bluetooth"], ["/leds", "LEDs", "Definir como as luzes do dongle se comportam"]] },
  sistema: { title: "Sistema", desc: "Atualizações, hora, espaço, hardware e backup.", items: [["/hora", "Data e hora", "Relógio, fuso horário e sincronização"], ["/atualizacoes", "Atualizações", "Ver e instalar atualizações disponíveis"], ["/status", "Status e saúde", "Temperatura, memória e armazenamento"], ["/desempenho", "Desempenho", "CPU, RAM e processos em execução"], ["/espaco", "Espaço em disco", "Uso do armazenamento e limpeza"], ["/hardware", "Hardware", "Placa, memória, eMMC, IMEI e MAC"], ["/nome-backup", "Nome, backup e reset", "Nome do dongle, cópia e restauração"]] },
  ajuda: { title: "Ajuda e recuperação", desc: "Perdi o acesso, como recuperar e dúvidas comuns.", items: [["/ajuda#senha", "Esqueci a senha", "Como recuperar pelo root ou pelo cabo USB"], ["/ajuda#wifi", "Não consigo conectar no Wi-Fi", "Verifique senha, sinal e o endereço novo"], ["/ajuda#4g", "Chip 4G não conecta", "APN, sinal, registro e crédito"]] },
  avancadas: { title: "Opções avançadas", desc: "Ferramentas para investigar e operar o sistema.", items: [["/logs", "Logs do sistema", "journalctl por serviço"], ["/diagnostico", "Diagnóstico de hardware", "Áudio, Bluetooth, vídeo USB e modem"], ["/recursos", "Memória por serviço", "RAM de cada serviço (PSS)"], ["/servicos", "Serviços do sistema", "O que sobe no boot: ligar e desligar"], ["/kernel", "Kernel e módulos", "Versão, parâmetros de boot e módulos"], ["/config-arquivo", "Arquivo de configuração", "A config central, com senhas ocultas"]] },
} as const

type Item = readonly [string, string, string]

function GoBack() { return <Link href="/" className="text-xs text-muted-foreground hover:text-foreground">← Voltar ao início</Link> }
function Action({ label, message = "Aplicando configuração" }: { label: string; message?: string }) {
  const { processar } = usePanel()
  return <Btn size="sm" onClick={() => processar({ mensagem: message, duracao: 700 })}>{label}</Btn>
}
function ListPage({ group }: { group: keyof typeof groups }) {
  const data = groups[group]
  const Icon = icons[group]
  return <div className="space-y-6"><PageHeader icon={Icon} title={data.title} desc={data.desc}><GoBack /></PageHeader><Card><RowGroup cols={2}>{data.items.map(([href, title, sub]) => <Row key={href} href={href} icon={icons[href.slice(1)] ?? ListTree} title={title} sub={sub} />)}</RowGroup></Card></div>
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
    if (!/^[a-z][a-z0-9_-]{2,31}$/.test(novoUser)) { setMsgUser({ tone: "warn", texto: "Use minúsculas, números, - ou _ (começando por letra)." }); return }
    await processar({ mensagem: "Trocando o nome de usuário", duracao: 8000, acao: "usuario-renomear", args: { atual: senhaRenom, novo: novoUser } })
    setSenhaRenom("")
    setMsgUser({ tone: "info", texto: "Se a senha estava certa, o usuário foi renomeado. As sessões SSH caem." })
  }

  const trocar = async () => {
    setMsg(null)
    if (nova !== conf) { setMsg({ tone: "warn", texto: "As duas senhas novas não são iguais." }); return }
    if (nova.length < 8) { setMsg({ tone: "warn", texto: "Use pelo menos 8 caracteres." }); return }
    await processar({
      mensagem: "Trocando a senha", duracao: 4000,
      acao: "set-password", args: { atual, nova, confirmacao: conf, encerrar },
    })
    setAtual(""); setNova(""); setConf("")
    setMsg({ tone: "info", texto: "Se a senha atual estava certa, a senha foi trocada." })
  }


  return <div className="space-y-6"><PageHeader icon={password ? KeyRound : UserRound} title={password ? "Senha de acesso" : "Conta e identidade"} desc={password ? "Uma senha forte protege o painel e o acesso administrativo." : "Identidade usada para administrar este dongle."}><GoBack /></PageHeader><Card><CardTitle>{password ? "Trocar senha" : "Administrador"}</CardTitle>{password ? <div className="max-w-xl space-y-4"><Field label="Senha atual"><Input type="password" value={atual} onChange={(e) => setAtual(e.target.value)} autoComplete="current-password" /></Field><Field label="Nova senha" hint="Use pelo menos 8 caracteres."><Input type="password" value={nova} onChange={(e) => setNova(e.target.value)} autoComplete="new-password" /></Field><Field label="Confirmar nova senha"><Input type="password" value={conf} onChange={(e) => setConf(e.target.value)} autoComplete="new-password" /></Field><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={encerrar} onChange={(e) => setEncerrar(e.target.checked)} /> Encerrar outras sessões</label><Btn variant="primary" onClick={trocar} disabled={!atual || !nova}>Trocar senha</Btn>{msg && <Notice tone={msg.tone}>{msg.tone === "info" && <Check className="mr-1 inline size-3.5" />}{msg.texto}</Notice>}</div> : <div className="space-y-5"><AvatarEditor /><div><p className="text-lg font-semibold">{PERFIL.nome || PERFIL.usuario}</p><p className="text-sm text-muted-foreground">@{PERFIL.usuario} · Administrador</p></div></div>}</Card></div>
}

function UsbPage() { const { dados, processar } = usePanel(); return <div className="space-y-6"><PageHeader icon={Usb} title="Aparelhos USB" desc="Escolha como a porta USB do dongle deve funcionar."><GoBack /></PageHeader><Card><CardTitle>Papel da porta</CardTitle><div className="grid gap-3 sm:grid-cols-2"><button onClick={() => processar({ mensagem: "Mudando a porta USB para host", duracao: 3000, acao: "usb-papel", args: { papel: "host" } })} className={cn("rounded-xl border p-4 text-left", dados.usb.papel === "host" && "border-brand bg-brand/5")}><p className="font-medium">Host</p><p className="mt-1 text-xs text-muted-foreground">Conectar pendrive, teclado ou placa de som.</p></button><button onClick={() => processar({ mensagem: "Mudando a porta USB para device", duracao: 3000, acao: "usb-papel", args: { papel: "device" } })} className={cn("rounded-xl border p-4 text-left", dados.usb.papel === "device" && "border-brand bg-brand/5")}><p className="font-medium">Device</p><p className="mt-1 text-xs text-muted-foreground">Ligar o dongle a um computador por USB.</p></button></div></Card><Card><CardTitle hint={`${dados.usb.aparelhos.length} detectados`}>Aparelhos conectados</CardTitle><RowGroup>{dados.usb.aparelhos.map(a => <Row key={a.id} icon={Usb} title={a.nome} sub={`${a.tipo} · ${a.id}`} action={<Pill tone="ok">detectado</Pill>} />)}</RowGroup></Card></div> }

function DataPage({ slug }: { slug: string }) {
  const { dados, saude, processar } = usePanel(); const Icon = icons[slug] ?? Settings2
  const generic: Record<string, { title: string; desc: string; body: React.ReactNode }> = {
    audio: { title: "Áudio", desc: "Placas, volume, microfone e saídas Bluetooth.", body: <><CardTitle>USB Audio Device</CardTitle><div className="space-y-4"><Field label="Saída"><Input value="Speaker · saída" readOnly /></Field><Field label="Volume"><input className="w-full accent-[var(--brand)]" type="range" defaultValue="65" /></Field><Field label="Entrada"><Input value="Mic · entrada" readOnly /></Field><Field label="Volume do microfone"><input className="w-full accent-[var(--brand)]" type="range" defaultValue="40" /></Field><Btn size="sm">Testar áudio</Btn></div></> },
    leds: { title: "LEDs", desc: "Defina como as luzes do dongle se comportam.", body: <RowGroup>{Object.entries(dados.leds).map(([id, value]) => <Row key={id} icon={Lightbulb} title={id.replace(":", " · ")} sub="Comportamento da luz" action={<Select defaultValue={value} onChange={(e) => processar({ mensagem: "Ajustando " + id, duracao: 1500, acao: "led-set", args: { led: id, gatilho: e.target.value } })}><option value="auto">Automático (OpenDongle)</option><option value="none">Apagado</option><option value="default-on">Aceso</option><option value="heartbeat">Piscando</option></Select>} />)}</RowGroup> },
    hora: { title: "Data e hora", desc: "Relógio, fuso horário e sincronização.", body: <div className="max-w-xl space-y-4"><Field label="Fuso horário"><Select defaultValue="America/Sao_Paulo"><option>America/Sao_Paulo</option><option>UTC</option></Select></Field><Toggle checked label="Sincronizar automaticamente pela internet" onChange={() => {}} /><Btn size="sm">Salvar horário</Btn></div> },
    atualizacoes: { title: "Atualizações", desc: "Mantenha o sistema seguro e atualizado.", body: <><div className="flex items-center justify-between rounded-lg bg-ok-soft/60 p-4"><div><p className="font-medium">Sistema atualizado</p><p className="text-xs text-muted-foreground">Última verificação: hoje às 01:42</p></div><Pill tone="ok">v0.8.4</Pill></div><div className="mt-4 flex gap-2"><Action label="Procurar atualizações" message="Procurando atualizações" /><Btn size="sm" variant="secondary">Ver histórico</Btn></div></> },
    status: { title: "Status e saúde", desc: "Uma leitura rápida da saúde do dongle.", body: <div className="grid grid-cols-2 gap-3 sm:grid-cols-3"><Stat label={<span className="flex items-center gap-1.5"><MemoryStick className="size-3.5" /> Memória RAM</span>} value={`${saude.ramPct}%`} bar={saude.ramPct} /><Stat label={<span className="flex items-center gap-1.5"><Thermometer className="size-3.5" /> Temperatura</span>} value={`${saude.tempC}°`} bar={saude.tempC / 0.9} /><Stat label={<span className="flex items-center gap-1.5"><HardDrive className="size-3.5" /> Disco</span>} value={`${saude.discoPct}%`} bar={saude.discoPct} /></div> },
    desempenho: { title: "Desempenho", desc: "CPU, RAM e processos em execução.", body: <><CardTitle>Uso atual</CardTitle><div className="space-y-4"><div><div className="mb-1 flex justify-between text-xs"><span>CPU</span><span>28%</span></div><MiniBar value={28} /></div><div><div className="mb-1 flex justify-between text-xs"><span>RAM</span><span>{saude.ramPct}%</span></div><MiniBar value={saude.ramPct} tone={saude.ramPct > 75 ? "warn" : "ok"} /></div></div><div className="mt-5"><CardTitle hint="4 processos">Processos mais ativos</CardTitle><RowGroup><Row title="opendongle.service" sub="8.5 MB PSS · principal" /><Row title="hostapd@wlan0.service" sub="3.1 MB PSS" /><Row title="bluetooth.service" sub="4.2 MB PSS" /></RowGroup></div></> },
    espaco: { title: "Espaço em disco", desc: "Uso do armazenamento e limpeza.", body: <><div className="flex items-center gap-4"><div className="flex size-20 items-center justify-center rounded-full border-[10px] border-ok text-lg font-semibold">34%</div><div><p className="font-medium">2,7 GB usados de 8 GB</p><p className="text-sm text-muted-foreground">Há espaço suficiente para atualizações.</p></div></div><div className="mt-5"><CardTitle>Ocupação</CardTitle><RowGroup><Row title="Sistema" sub="1,8 GB" /><Row title="Logs" sub="412 MB" /><Row title="Dados do usuário" sub="486 MB" /></RowGroup></div><div className="mt-4"><Action label="Analisar agora" message="Analisando espaço" /></div></> },
    hardware: { title: "Hardware", desc: "Identificação dos componentes do dongle.", body: <RowGroup><Row icon={Cpu} title="Placa" sub="OpenDongle Rev. B" /><Row icon={MemoryStick} title="Memória" sub="1 GB LPDDR4" /><Row icon={HardDrive} title="eMMC" sub="8 GB · 34% usado" /><Row icon={Wifi} title="MAC Wi-Fi" sub="AA:BB:CC:DD:EE:FF" /><Row icon={Radio} title="IMEI" sub={dados.modem.imei} /></RowGroup> },
    "nome-backup": { title: "Nome, backup e reset", desc: "Identidade do aparelho, cópia e restauração.", body: <><Field label="Nome do dongle"><Input defaultValue="OpenDongle" /></Field><div className="mt-4 flex flex-wrap gap-2"><Btn size="sm">Salvar nome</Btn><Btn size="sm" variant="secondary"><Download className="size-3.5" /> Baixar backup da configuração</Btn><Btn size="sm" variant="secondary">Restaurar backup</Btn></div><Notice>Voltar à configuração de fábrica apaga as credenciais e configurações atuais.</Notice><Btn size="sm" variant="danger">Voltar à configuração de fábrica</Btn></> },
  }
  const page = generic[slug]
  return <div className="space-y-6"><PageHeader icon={Icon} title={page?.title ?? slug} desc={page?.desc ?? "Configuração do OpenDongle."}><GoBack /></PageHeader><Card>{page?.body ?? <><CardTitle>Configuração</CardTitle><p className="text-sm text-muted-foreground">Esta área reúne as opções avançadas do dongle.</p><div className="mt-4"><Action label="Salvar configuração" /></div></>}</Card></div>
}

function AdvancedLeaf({ slug }: { slug: string }) {
  const { dados, processar } = usePanel(); const Icon = icons[slug] ?? Wrench
  if (slug === "servicos") return <div className="space-y-6"><PageHeader icon={Server} title="Serviços do sistema" desc="O que sobe no boot: ligar e desligar."><GoBack /></PageHeader><Card><RowGroup>{dados.servicos.map(s => <Row key={s.nome} icon={Server} title={s.nome} sub={`${s.ramMb.toFixed(1)} MB · ${s.rodando ? "rodando" : "parado"}`} action={s.essencial ? <Pill tone="neutral">essencial</Pill> : <Toggle checked={s.habilitado} label="" onChange={(v) => processar({ mensagem: (v ? "Ligando " : "Desligando ") + s.nome, duracao: 4000, acao: "servico-set", args: { nome: s.nome, ligar: v } })} />} />)}</RowGroup></Card></div>
  const title = { logs: "Logs do sistema", diagnostico: "Diagnóstico de hardware", kernel: "Kernel e módulos", recursos: "Memória por serviço", "config-arquivo": "Arquivo de configuração" }[slug as string] ?? "Opções avançadas"
  return <div className="space-y-6"><PageHeader icon={Icon} title={title} desc="Ferramenta de manutenção para investigação do sistema."><GoBack /></PageHeader><Card><CardTitle>{slug === "logs" ? "journalctl" : slug === "diagnostico" ? "Testes disponíveis" : "Detalhes do sistema"}</CardTitle>{slug === "diagnostico" ? <RowGroup><Row icon={AudioLines} title="Saída de áudio" sub="Teste de reprodução e microfone" action={<Action label="Testar" message="Testando áudio" />} /><Row icon={Bluetooth} title="Bluetooth" sub="Rádio e pareamento" action={<Action label="Testar" message="Testando Bluetooth" />} /><Row icon={Usb} title="Vídeo USB" sub="Dispositivo de captura" action={<Action label="Testar" message="Testando vídeo USB" />} /><Row icon={Radio} title="Modem 4G" sub="SIM, registro e sinal" action={<Action label="Testar" message="Testando modem" />} /></RowGroup> : slug === "logs" ? <><pre className="max-h-80 overflow-auto rounded-lg bg-muted p-4 text-xs leading-6 text-muted-foreground">{`2026-09-19 01:42:08 opendongle.service started\n2026-09-19 01:42:09 hostapd wlan0 ready\n2026-09-19 01:42:10 bluetooth.service connected Fone do Lucas\n2026-09-19 01:42:12 dnsmasq DHCP lease 192.168.100.10`}</pre><div className="mt-4"><Action label="Atualizar logs" message="Atualizando logs" /></div></> : <><div className="rounded-lg bg-muted p-4 font-mono text-xs leading-6 text-muted-foreground">{slug === "kernel" ? "Linux 6.6.31 · arm64\nMódulos: qmi_wwan, btusb, snd_usb_audio" : slug === "recursos" ? "opendongle.service      8.5 MB\ndnsmasq.service         2.8 MB\nhostapd@wlan0.service   3.1 MB" : "{\n  \"network\": { \"mode\": \"hotspot\" },\n  \"services\": { \"bluetooth\": true }\n}"}</div><div className="mt-4"><Btn size="sm" variant="secondary">Atualizar</Btn></div></>}</Card></div>
}

function BluetoothPage() {
  const { dados, processar } = usePanel(); const bt = dados.bluetooth
  const acao = (mensagem: string, a: string, args: Record<string, unknown>, duracao = 6000) =>
    () => processar({ mensagem, duracao, acao: a, args })
  return <div className="space-y-6"><PageHeader icon={Bluetooth} title="Bluetooth" desc="Pareie e gerencie fones, caixas, teclados e controles."><GoBack /></PageHeader>
    <Card><div className="flex flex-wrap items-center justify-between gap-3"><div><CardTitle hint={bt.ligado ? "ligado" : "desligado"}>Rádio Bluetooth</CardTitle><p className="text-sm text-muted-foreground">{bt.nome} · {bt.mac}</p></div><Toggle checked={bt.ligado} label="Bluetooth ligado" onChange={(v) => processar({ mensagem: v ? "Ligando o Bluetooth" : "Desligando o Bluetooth", duracao: 4000, acao: "bt-ligar", args: { ligar: v } })} /></div></Card>
    {bt.ligado && <><Card><CardTitle hint={`${bt.pareados.length} aparelhos`}>Aparelhos pareados</CardTitle>{bt.pareados.length ? <RowGroup>{bt.pareados.map(d => <Row key={d.mac} icon={Bluetooth} title={d.nome} sub={`${d.tipo || "aparelho"} · ${d.mac}${d.bateria != null ? " · " + d.bateria + "%" : ""}`} action={<div className="flex items-center gap-2">{d.conectado ? <Btn size="sm" variant="secondary" onClick={acao("Desconectando " + d.nome, "bt-desconectar", { mac: d.mac }, 5000)}>Desconectar</Btn> : <Btn size="sm" variant="primary" onClick={acao("Conectando " + d.nome, "bt-conectar", { mac: d.mac }, 12000)}>Conectar</Btn>}<Btn size="sm" variant="ghost" onClick={acao("Esquecendo " + d.nome, "bt-esquecer", { mac: d.mac }, 4000)}>Esquecer</Btn></div>} />)}</RowGroup> : <p className="text-sm text-muted-foreground">Nenhum aparelho pareado ainda.</p>}<div className="mt-4 flex gap-2"><Btn size="sm" onClick={() => processar({ mensagem: "Procurando aparelhos Bluetooth", duracao: 12000, acao: "bt-buscar" })}><Search className="size-3.5" /> Procurar aparelhos</Btn><Btn size="sm" variant="secondary" onClick={() => processar({ mensagem: "Deixando o dongle visível", duracao: 2000, acao: "bt-visivel", args: { visivel: true } })}>Tornar visível</Btn></div></Card>
    {bt.novos.length > 0 && <Card><CardTitle hint={`${bt.novos.length} encontrados`}>Aparelhos encontrados</CardTitle><RowGroup>{bt.novos.map(d => <Row key={d.mac} icon={Bluetooth} title={d.nome} sub={`${d.tipo || "aparelho"} · ${d.mac}`} action={<Btn size="sm" variant="primary" onClick={acao("Pareando " + d.nome, "bt-parear", { mac: d.mac }, 20000)}>Parear</Btn>} />)}</RowGroup></Card>}</>}
  </div>
}

function VolumeLinha({ label, sub, volume, mudo, onVol, onMudo, onTestar }: { label: string; sub?: string; volume: number; mudo: boolean; onVol: (v: number) => void; onMudo: (v: boolean) => void; onTestar?: () => void }) {
  return <div className="border-b border-border py-3 last:border-b-0"><div className="flex items-center justify-between gap-3"><div className="min-w-0"><p className="truncate text-sm font-medium">{label}</p>{sub && <p className="truncate text-xs text-muted-foreground">{sub}</p>}</div><div className="flex items-center gap-2">{onTestar && <Btn size="sm" variant="secondary" onClick={onTestar}>Tocar teste</Btn>}<Toggle checked={!mudo} label="" onChange={(v) => onMudo(!v)} /></div></div><input type="range" min={0} max={100} defaultValue={volume} className="mt-2 w-full accent-brand" onPointerUp={(e) => onVol(Number((e.target as HTMLInputElement).value))} onKeyUp={(e) => onVol(Number((e.target as HTMLInputElement).value))} /></div>
}

function AudioPage() {
  const { dados, processar } = usePanel(); const a = dados.audio
  return <div className="space-y-6"><PageHeader icon={Volume2} title="Áudio" desc="Placas de som USB, fones Bluetooth, volume e microfone."><GoBack /></PageHeader>
    <Card><div className="flex items-center justify-between gap-3"><div><CardTitle hint={a.bluetoothLigado ? "ligado" : "desligado"}>Áudio por Bluetooth</CardTitle><p className="text-sm text-muted-foreground">Liga o PipeWire para tocar em fones e caixas.</p></div><Toggle checked={a.bluetoothLigado} label="Áudio Bluetooth" onChange={(v) => processar({ mensagem: v ? "Preparando o áudio Bluetooth" : "Desligando o áudio Bluetooth", duracao: 15000, acao: "audio-bt-set", args: { ligar: v } })} /></div></Card>
    {a.placas.length ? a.placas.map(pl => <Card key={pl.id}><div className="flex items-center justify-between gap-3"><CardTitle hint={pl.padrao ? "padrão" : undefined}>{pl.nome}</CardTitle>{!pl.padrao && <Btn size="sm" variant="secondary" onClick={() => processar({ mensagem: "Definindo placa padrão", duracao: 2000, acao: "audio-padrao", args: { placa: pl.id } })}>Usar como padrão</Btn>}</div>{pl.controles.map(c => <VolumeLinha key={c.nome} label={c.nome} sub={c.tipo} volume={c.volume} mudo={c.mudo} onVol={(v) => processar({ mensagem: "Ajustando volume", duracao: 800, acao: "audio-ajustar", args: { placa: pl.id, controle: c.nome, volume: v } })} onMudo={(m) => processar({ mensagem: m ? "Mudo" : "Ativando som", duracao: 800, acao: "audio-ajustar", args: { placa: pl.id, controle: c.nome, mudo: m } })} onTestar={c.tipo === "saída" ? () => processar({ mensagem: "Tocando som de teste", duracao: 3000, acao: "audio-testar", args: { placa: pl.id } }) : undefined} />)}</Card>) : <Card><p className="text-sm text-muted-foreground">Nenhuma placa de som USB detectada. Plugue uma placa na porta USB (modo host).</p></Card>}
    {a.bluetoothLigado && (a.btSaidas.length > 0 || a.btEntradas.length > 0) && <Card><CardTitle>Fones e caixas Bluetooth</CardTitle>{a.btSaidas.map(s => <div key={s.id}><VolumeLinha label={s.nome} sub="saída" volume={s.volume} mudo={s.mudo} onVol={(v) => processar({ mensagem: "Ajustando volume", duracao: 800, acao: "audio-bt-ajustar", args: { no: s.id, volume: v } })} onMudo={(m) => processar({ mensagem: m ? "Mudo" : "Ativando som", duracao: 800, acao: "audio-bt-ajustar", args: { no: s.id, mudo: m } })} />{a.btModos[String(s.id)] && <div className="pb-3"><Segmented value={a.btModos[String(s.id)]} options={[{ value: "musica", label: "Música" }, { value: "chamada", label: "Chamada (com microfone)" }]} onChange={(m) => processar({ mensagem: "Trocando o modo do áudio", duracao: 4000, acao: "audio-bt-modo", args: { dev: s.id, modo: m } })} /></div>}</div>)}{a.btEntradas.map(e => <VolumeLinha key={e.id} label={e.nome} sub="microfone" volume={e.volume} mudo={e.mudo} onVol={(v) => processar({ mensagem: "Ajustando microfone", duracao: 800, acao: "audio-bt-ajustar", args: { no: e.id, volume: v } })} onMudo={(m) => processar({ mensagem: m ? "Mudo" : "Ativando microfone", duracao: 800, acao: "audio-bt-ajustar", args: { no: e.id, mudo: m } })} />)}</Card>}
  </div>
}

function TorPage() {
  const { dados, processar } = usePanel(); const on = dados.tor.ativo
  return <div className="space-y-6"><PageHeader icon={ShieldCheck} title="Navegação via Tor" desc="Faz todo o tráfego dos aparelhos da rede passar pela rede Tor."><GoBack /></PageHeader><Card><div className="flex items-center justify-between gap-3"><div><CardTitle hint={on ? "ligado" : "desligado"}>Rede Tor</CardTitle><p className="text-sm text-muted-foreground">Mais privacidade, porém mais lento. Alguns sites podem bloquear.</p></div><Toggle checked={on} label="Tor" onChange={(v) => processar({ mensagem: v ? "Ligando o Tor (pode baixar o pacote)" : "Desligando o Tor", duracao: 20000, acao: "tor-set", args: { ligar: v } })} /></div></Card></div>
}

function RemotoPage() {
  const { dados, processar } = usePanel(); const r = dados.remoto
  return <div className="space-y-6"><PageHeader icon={Network} title="Acesso remoto" desc="Acesse o dongle de longe, de qualquer lugar, via Tailscale."><GoBack /></PageHeader><Card><div className="flex items-center justify-between gap-3"><div><CardTitle hint={r.ativo ? "ligado" : "desligado"}>Tailscale</CardTitle><p className="text-sm text-muted-foreground">Cria um endereço privado para chegar ao painel de fora da rede.</p></div><Toggle checked={r.ativo} label="Acesso remoto" onChange={(v) => processar({ mensagem: v ? "Ligando o acesso remoto (pode baixar o pacote)" : "Desligando o acesso remoto", duracao: 20000, acao: "remoto-set", args: { ligar: v, lan: r.lan, saida: r.saida } })} /></div>{r.ativo && <div className="mt-4 space-y-3 border-t border-border pt-4"><Toggle checked={r.lan} label="Compartilhar a rede local com meus outros aparelhos" onChange={(v) => processar({ mensagem: "Aplicando", duracao: 4000, acao: "remoto-set", args: { ligar: true, lan: v, saida: r.saida } })} /><Toggle checked={r.saida} label="Usar o dongle como saída de internet (exit node)" onChange={(v) => processar({ mensagem: "Aplicando", duracao: 4000, acao: "remoto-set", args: { ligar: true, lan: r.lan, saida: v } })} /></div>}</Card></div>
}

function FirewallPage() {
  const { dados, processar } = usePanel(); const fw = dados.firewall
  const [nome, setNome] = useState(""); const [proto, setProto] = useState("tcp"); const [pe, setPe] = useState(""); const [ip, setIp] = useState(""); const [pi, setPi] = useState("")
  const setFlag = (campo: string, v: boolean) => processar({ mensagem: "Aplicando firewall", duracao: 4000, acao: "fw-set", args: { wifiClienteConfiavel: fw.wifiClienteConfiavel, sshPelaWan: fw.sshPelaWan, painelPelaWan: fw.painelPelaWan, [campo]: v } })
  const adicionar = async () => { await processar({ mensagem: "Adicionando redirecionamento", duracao: 4000, acao: "redir-add", args: { nome, proto, portaExterna: Number(pe), ip, portaInterna: Number(pi) } }); setNome(""); setPe(""); setIp(""); setPi("") }
  return <div className="space-y-6"><PageHeader icon={LockKeyhole} title="Firewall e portas" desc="A rede local sempre tem acesso; o 4G fica fechado exceto o que você liberar."><GoBack /></PageHeader>
    <Card><CardTitle>Acesso pela internet (4G)</CardTitle><div className="space-y-3"><Toggle checked={fw.wifiClienteConfiavel} label="Confiar na rede Wi-Fi de casa (acesso liberado por ela)" onChange={(v) => setFlag("wifiClienteConfiavel", v)} /><Toggle checked={fw.sshPelaWan} label="Liberar SSH pela internet (porta 22)" onChange={(v) => setFlag("sshPelaWan", v)} /><Toggle checked={fw.painelPelaWan} label="Liberar o painel pela internet (porta 80)" onChange={(v) => setFlag("painelPelaWan", v)} /></div></Card>
    <Card><CardTitle hint={`${fw.redirecionamentos.length}`}>Redirecionamento de portas</CardTitle>{fw.redirecionamentos.length ? <RowGroup>{fw.redirecionamentos.map(x => <Row key={x.nome} icon={Network} title={x.nome} sub={`${x.proto} ${x.portaExterna} → ${x.ip}:${x.portaInterna}`} action={<Btn size="sm" variant="ghost" onClick={() => processar({ mensagem: "Removendo", duracao: 3000, acao: "redir-rm", args: { nome: x.nome } })}>Remover</Btn>} />)}</RowGroup> : <p className="text-sm text-muted-foreground">Nenhum redirecionamento.</p>}<div className="mt-4 grid gap-2 sm:grid-cols-2"><Field label="Nome"><Input value={nome} onChange={e => setNome(e.target.value)} /></Field><Field label="Protocolo"><Select value={proto} onChange={e => setProto(e.target.value)}><option value="tcp">tcp</option><option value="udp">udp</option></Select></Field><Field label="Porta externa"><Input value={pe} onChange={e => setPe(e.target.value)} /></Field><Field label="IP interno"><Input value={ip} onChange={e => setIp(e.target.value)} placeholder="192.168.100.x" /></Field><Field label="Porta interna"><Input value={pi} onChange={e => setPi(e.target.value)} /></Field></div><Btn variant="primary" className="mt-3" onClick={adicionar} disabled={!nome || !pe || !ip || !pi}>Adicionar redirecionamento</Btn></Card></div>
}

function HoraPage() {
  const { dados, processar } = usePanel(); const h = dados.hora
  const [fuso, setFuso] = useState(h.fuso); const [auto, setAuto] = useState(h.automatica)
  const FUSOS = ["America/Sao_Paulo", "America/Manaus", "America/Belem", "America/Fortaleza", "America/Cuiaba", "America/Rio_Branco", "America/Noronha", "UTC"]
  return <div className="space-y-6"><PageHeader icon={Clock3} title="Data e hora" desc="Relógio, fuso horário e sincronização automática."><GoBack /></PageHeader><Card>{h.agora && <p className="mb-4 text-sm text-muted-foreground">Agora no dongle: <span className="font-medium text-foreground">{h.agora}</span></p>}<div className="max-w-xl space-y-4"><Field label="Fuso horário"><Select value={fuso} onChange={e => setFuso(e.target.value)}>{FUSOS.map(f => <option key={f} value={f}>{f}</option>)}</Select></Field><Toggle checked={auto} label="Acertar o relógio automaticamente pela internet" onChange={setAuto} /><Btn variant="primary" onClick={() => processar({ mensagem: "Salvando data e hora", duracao: 3000, acao: "hora-set", args: { automatica: auto, fuso } })}>Salvar horário</Btn></div></Card></div>
}

function AtualizacoesPage() {
  const { processar } = usePanel()
  return <div className="space-y-6"><PageHeader icon={Download} title="Atualizações" desc="Correções e melhorias do sistema."><GoBack /></PageHeader><Card><CardTitle>Sistema</CardTitle><p className="text-sm text-muted-foreground">Verifique e instale atualizações do Debian. Precisa de internet.</p><div className="mt-4 flex gap-2"><Btn variant="secondary" onClick={() => processar({ mensagem: "Procurando atualizações", duracao: 25000, acao: "atualizacoes", args: { instalar: false } })}><RefreshCw className="size-4" /> Verificar</Btn><Btn variant="primary" onClick={() => processar({ mensagem: "Instalando atualizações", duracao: 120000, acao: "atualizacoes", args: { instalar: true } })}><Download className="size-4" /> Instalar</Btn></div></Card></div>
}

function useApi<T>(rota: string, intervalo = 0) {
  const [dados, setDados] = useState<T | null>(null)
  const [carregando, setCarregando] = useState(true)
  useEffect(() => {
    let vivo = true
    const puxar = async () => { const d = await apiGet<T>(rota); if (vivo) { setDados(d); setCarregando(false) } }
    puxar()
    if (intervalo) {
      const id = setInterval(() => { if (!document.hidden) puxar() }, intervalo)
      return () => { vivo = false; clearInterval(id) }
    }
    return () => { vivo = false }
  }, [rota, intervalo])
  return { dados, carregando }
}

function StatusPage() {
  const { dados } = useApi<{ saude: any; estado: any }>("/api/status", 5000)
  const sa = dados?.saude, st = dados?.estado
  const ramPct = sa?.ram ? Math.round(100 - sa.ram.disponivel_kb * 100 / (sa.ram.total_kb || 1)) : 0
  return <div className="space-y-6"><PageHeader icon={Activity} title="Status e saúde" desc="Como está o dongle agora."><GoBack /></PageHeader>
    {!dados ? <Card><p className="text-sm text-muted-foreground">Carregando…</p></Card> : <>
    <Card><div className="flex flex-wrap items-center gap-3"><Pill tone={st?.internet ? "ok" : "warn"}>{st?.internet ? "conectado à internet" : "sem internet"}</Pill><span className="text-sm text-muted-foreground">{st?.modo === "wifi" ? `Wi-Fi · ${st?.endereco?.ssid ?? ""}` : st?.modo === "hotspot" ? `Hotspot · ${st?.ssidHotspot ?? ""}` : "—"}</span></div>{st?.endereco && <p className="mt-3 text-sm">Endereço nesta rede: <b>{st.endereco.ip}</b>{!st.endereco.agora && " (último visto)"}</p>}</Card>
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <Stat label="CPU (1 min)" value={sa?.cpu ? `${sa.cpu.carga_1m?.toFixed?.(2) ?? sa.cpu.carga_1m}` : "—"} />
      <Stat label="RAM usada" value={`${ramPct}%`} tone={ramPct > 85 ? "err" : ramPct > 70 ? "warn" : ""} bar={ramPct} />
      <Stat label="Disco" value={`${sa?.disco_raiz?.usado_pct ?? 0}%`} bar={sa?.disco_raiz?.usado_pct ?? 0} />
      <Stat label="Temperatura" value={sa?.temp_cpu_c != null ? `${Math.round(sa.temp_cpu_c)}°` : "—"} tone={sa?.temp_cpu_c > 70 ? "err" : sa?.temp_cpu_c > 60 ? "warn" : ""} />
    </div>
    <Card><CardTitle>Detalhes</CardTitle><RowGroup cols={2}>
      <Row title="Memória" sub={sa?.ram ? `${Math.round(sa.ram.disponivel_kb/1024)} MB livres de ${Math.round(sa.ram.total_kb/1024)} MB` : "—"} />
      <Row title="Disco raiz" sub={sa?.disco_raiz ? `${sa.disco_raiz.usado_gb} GB de ${sa.disco_raiz.total_gb} GB` : "—"} />
      <Row title="Ligado há" sub={sa?.uptime_s != null ? `${Math.floor(sa.uptime_s/3600)}h ${Math.floor(sa.uptime_s%3600/60)}min` : "—"} />
      <Row title="Núcleos" sub={sa?.cpu?.nucleos ?? "—"} />
    </RowGroup>{sa?.temperaturas_c && <div className="mt-3 text-xs text-muted-foreground">{Object.entries(sa.temperaturas_c).map(([k,v]) => `${k}: ${v}°`).join(" · ")}</div>}</Card>
    <RebootCard />
    </>}
  </div>
}

function DesempenhoPage() {
  const { dados } = useApi<any>("/api/desempenho", 2500)
  const { processar } = usePanel()
  if (!dados?.ok) return <div className="space-y-6"><PageHeader icon={Cpu} title="Desempenho" desc="CPU, memória e processos ao vivo."><GoBack /></PageHeader><Card><p className="text-sm text-muted-foreground">{dados ? "Não foi possível ler o desempenho." : "Carregando…"}</p></Card></div>
  return <div className="space-y-6"><PageHeader icon={Cpu} title="Desempenho" desc="CPU, memória e processos — atualiza sozinho."><GoBack /></PageHeader>
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <Stat label="Carga (1 min)" value={`${dados.carga?.[0] ?? "—"}`} />
      <Stat label="RAM livre" value={`${dados.ram?.disponivel_mb ?? "—"} MB`} bar={dados.ram ? Math.round(100 - dados.ram.disponivel_mb*100/(dados.ram.total_mb||1)) : 0} />
      <Stat label="Swap (zram)" value={`${dados.swap?.usado_mb ?? 0} MB`} />
      <Stat label="Núcleos" value={`${dados.nucleos ?? "—"}`} />
    </div>
    <Card><CardTitle>Processos que mais usam</CardTitle><RowGroup>{(dados.processos || []).slice(0,8).map((p: any) => <Row key={p.pid} title={p.nome} sub={`PID ${p.pid} · CPU ${p.cpu}% · ${p.ram_mb} MB`} action={p.protegido ? <Pill tone="neutral">protegido</Pill> : <Btn size="sm" variant="ghost" onClick={() => processar({ mensagem: "Encerrando " + p.nome, duracao: 2000, acao: "processo-encerrar", args: { pid: p.pid } })}>Encerrar</Btn>} />)}</RowGroup></Card>
  </div>
}

function EspacoPage() {
  const { dados, carregando } = useApi<any>("/api/espaco")
  const { processar } = usePanel()
  const lib = dados?.liberavel
  const totalLib = lib ? (lib.cache_apt_mb + lib.logs_antigos_mb + lib.journal_mb) : 0
  return <div className="space-y-6"><PageHeader icon={HardDrive} title="Espaço em disco" desc="O que ocupa o armazenamento e como liberar."><GoBack /></PageHeader>
    {carregando ? <Card><p className="text-sm text-muted-foreground">Carregando…</p></Card> : <>
    <Card><CardTitle>Discos</CardTitle><RowGroup>{(dados?.discos || []).map((d: any) => <Row key={d.ponto} title={d.nome} sub={`${d.ponto} · ${Math.round((d.total_mb-d.livre_mb)/1024*10)/10} GB de ${Math.round(d.total_mb/1024*10)/10} GB`} action={<div className="w-28"><MiniBar value={d.usado_pct} tone={d.usado_pct > 90 ? "err" : d.usado_pct > 75 ? "warn" : "ok"} /></div>} />)}</RowGroup></Card>
    <Card><CardTitle hint={`${totalLib} MB`}>Liberar espaço</CardTitle><p className="text-sm text-muted-foreground">Cache do APT: {lib?.cache_apt_mb ?? 0} MB · logs antigos: {lib?.logs_antigos_mb ?? 0} MB · journal: {lib?.journal_mb ?? 0} MB</p><div className="mt-4 flex gap-2"><Btn size="sm" variant="secondary" onClick={() => processar({ mensagem: "Analisando o disco", duracao: 8000, acao: "espaco-analisar" })}>Analisar</Btn><Btn size="sm" variant="primary" disabled={!totalLib} onClick={() => processar({ mensagem: "Liberando espaço", duracao: 10000, acao: "espaco-liberar" })}>Liberar {totalLib} MB</Btn></div></Card>
    </>}
  </div>
}

function HardwarePage() {
  const { dados, carregando } = useApi<any>("/api/hardware")
  const h = dados
  return <div className="space-y-6"><PageHeader icon={Router} title="Hardware" desc="Identificação real dos componentes do dongle."><GoBack /></PageHeader>
    {carregando ? <Card><p className="text-sm text-muted-foreground">Carregando…</p></Card> : !h?.ok ? <Card><p className="text-sm text-muted-foreground">Não foi possível ler o hardware.</p></Card> : <>
    <Card><CardTitle>{h.placa}{h.compativel === false && " (não homologada)"}</CardTitle><RowGroup cols={2}>
      <Row icon={Cpu} title="Processador" sub={`${h.soc} · ${h.cpu}`} />
      <Row icon={Cpu} title="Núcleos" sub={`${h.nucleos} × ${h.mhz} MHz · ${h.governor}`} />
      <Row icon={MemoryStick} title="Memória" sub={`${h.ram_mb} MB`} />
      <Row icon={HardDrive} title="eMMC" sub={h.emmc ? `${h.emmc.modelo} · ${h.emmc.tamanho_gb} GB · desgaste ${h.emmc.desgaste}` : "—"} />
      <Row icon={Wifi} title="Wi-Fi" sub={h.wifi ? `${h.wifi.driver} · ${h.wifi.mac}` : "—"} />
      <Row icon={Bluetooth} title="Bluetooth" sub={h.bluetooth_mac || "—"} />
      <Row icon={Radio} title="Modem 4G" sub={h.modem ? `${h.modem.firmware || ""} ${h.modem.imei ? "· IMEI " + h.modem.imei : ""}` : "—"} />
      <Row icon={Usb} title="MAC USB" sub={h.usb_mac || "—"} />
    </RowGroup></Card>
    <Card><CardTitle>Sistema</CardTitle><RowGroup cols={2}>
      <Row title="Kernel" sub={h.kernel} />
      <Row title="Sistema" sub={h.sistema} />
      <Row title="Ligado há" sub={h.ligado_ha} />
    </RowGroup></Card>
    </>}
  </div>
}

function RebootCard() {
  const [fase, setFase] = useState<"" | "reiniciando" | "desligando">("")
  const energia = async (acao: "reboot" | "poweroff") => {
    const txt = acao === "reboot" ? "reiniciando" : "desligando"
    if (!confirm(acao === "reboot" ? "Reiniciar o dongle agora?" : "Desligar o dongle? Para ligar de novo, tire e recoloque na tomada.")) return
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
  return <><Card><CardTitle>Energia</CardTitle><div className="flex gap-2"><Btn size="sm" variant="secondary" onClick={() => energia("reboot")}><RefreshCw className="size-4" /> Reiniciar</Btn><Btn size="sm" variant="danger" onClick={() => energia("poweroff")}><Zap className="size-4" /> Desligar</Btn></div></Card>
    {fase && <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/95 px-6 text-center"><div className="max-w-sm space-y-4"><RefreshCw className="mx-auto size-8 animate-spin text-brand" /><h2 className="text-lg font-semibold">{fase === "reiniciando" ? "Reiniciando o dongle…" : "Desligando o dongle…"}</h2><p className="text-sm text-muted-foreground">{fase === "reiniciando" ? "Isso leva cerca de 40 segundos. Esta página volta sozinha quando o dongle estiver pronto — não feche." : "Pode tirar da tomada quando as luzes apagarem. Para ligar de novo, recoloque na tomada."}</p></div></div>}
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
  if (["logs", "diagnostico", "kernel", "recursos", "servicos", "config-arquivo"].includes(slug)) return <AdvancedLeaf slug={slug} />
  return <DataPage slug={slug || "sistema"} />
}
