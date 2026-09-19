# Painel OpenDongle (front-end)

Interface web do dongle: app Next.js (React) exportado como **bundle estático**.
O dongle não roda Node — ele só serve os arquivos e responde a API JSON
(`opendongle_api.py` + rotas `/api/*` em `opendongle_web.py`). Os dados e as
ações vêm todos de `lib/panel/store.tsx`, que fala com essa API.

## Desenvolver

```bash
npm install
npm run dev          # http://localhost:3000 (aponte o fetch pro dongle se quiser dados reais)
```

## Gerar o bundle que vai pro dongle

```bash
npm run build        # gera out/ (export estático)
tar czf dist.tgz -C out .
```

O `dist.tgz` versionado aqui é o que o instalador (`core/instalar_opendongle.py`)
embarca em `/opt/opendongle/painel`. **Recompile e regenere o `dist.tgz` sempre
que mudar o front.** Sem o bundle no dongle, o painel cai no modo antigo
(HTML renderizado no servidor) — a flag é a existência da pasta.
