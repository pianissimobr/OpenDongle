import { SlugView } from "./slug-view"

// output:export precisa saber quais rotas gerar. São as que não têm página
// própria em app/ (essas o Next resolve sozinho). Uma rota fora desta lista
// cai no fallback do próprio SlugView.
export function generateStaticParams() {
  return [
  { slug: ["perfil"] },
  { slug: ["senha"] },
  { slug: ["dispositivos"] },
  { slug: ["bluetooth"] },
  { slug: ["usb"] },
  { slug: ["audio"] },
  { slug: ["leds"] },
  { slug: ["sistema"] },
  { slug: ["hora"] },
  { slug: ["atualizacoes"] },
  { slug: ["status"] },
  { slug: ["desempenho"] },
  { slug: ["espaco"] },
  { slug: ["hardware"] },
  { slug: ["nome-backup"] },
  { slug: ["ajuda"] },
  { slug: ["avancadas"] },
  { slug: ["logs"] },
  { slug: ["diagnostico"] },
  { slug: ["kernel"] },
  { slug: ["recursos"] },
  { slug: ["servicos"] },
  { slug: ["config-arquivo"] },
  { slug: ["tor"] },
  { slug: ["remoto"] },
  { slug: ["firewall"] },
  ]
}

export default async function Page({ params }: { params: Promise<{ slug?: string[] }> }) {
  const { slug } = await params
  return <SlugView slug={slug?.[0] ?? ""} />
}
