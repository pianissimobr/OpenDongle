// Reduz a imagem escolhida a um quadrado de `lado`px e devolve um data URL
// JPEG. Roda no navegador (canvas) — o dongle recebe algo pequeno e pronto.
export async function fotoParaDataUrl(file: File, lado = 256): Promise<string> {
  const url = URL.createObjectURL(file)
  try {
    const img = await new Promise<HTMLImageElement>((res, rej) => {
      const i = new Image()
      i.onload = () => res(i)
      i.onerror = () => rej(new Error("imagem inválida"))
      i.src = url
    })
    const c = document.createElement("canvas")
    c.width = c.height = lado
    const ctx = c.getContext("2d")
    if (!ctx) throw new Error("sem canvas")
    const s = Math.min(img.width, img.height)           // recorte quadrado central
    ctx.drawImage(img, (img.width - s) / 2, (img.height - s) / 2, s, s, 0, 0, lado, lado)
    return c.toDataURL("image/jpeg", 0.85)
  } finally {
    URL.revokeObjectURL(url)
  }
}
