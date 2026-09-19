/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',              // bundle estático: o dongle serve, sem Node
  trailingSlash: true,           // /wifi/ -> wifi/index.html (recarga direta funciona)
  typescript: { ignoreBuildErrors: true },
  images: { unoptimized: true },
}

export default nextConfig
