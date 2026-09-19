import type { Metadata, Viewport } from 'next'
import './globals.css'
import { PanelProvider } from '@/lib/panel/store'
import { Shell } from '@/components/panel/shell'

export const metadata: Metadata = {
  title: 'OpenDongle — Painel de administração',
  description:
    'Painel para configurar seu dongle: internet, Wi-Fi, dispositivos, áudio, rede e sistema, com uma interface minimalista.',
  generator: 'v0.app',
}

export const viewport: Viewport = {
  colorScheme: 'light dark',
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: 'white' },
    { media: '(prefers-color-scheme: dark)', color: 'black' },
  ],
}

const noFlash = `(function(){try{var t=localStorage.getItem('tema-ux');var e=document.documentElement;if(t==='escuro')e.classList.add('dark');else if(t==='claro')e.classList.add('light');}catch(_){}})();`

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="pt-BR" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: noFlash }} />
      </head>
      <body className="antialiased">
        <PanelProvider>
          <Shell>{children}</Shell>
        </PanelProvider>
      </body>
    </html>
  )
}
