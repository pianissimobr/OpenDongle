# Estrutura do projeto

## core/ — o fluxo principal (preparar um dongle)
Rode a partir daqui. O orquestrador faz tudo:
```
cd core
python3 opendongle_completo.py
```
- `opendongle_completo.py` — orquestrador (instala + otimiza + painel)
- `opendongle_autoinstall.py` — instala o Debian (backup, flash, verificação)
- `otimizar_dongle.py` — otimizações (zram, logs em RAM, noatime…)
- `instalar_opendongle.py` — instala o painel web + CLI + uplink_guard
- `setup_estrutura.py` — baixa firmware e loader
- `install.sh` — dependências do PC
- `opendongle/` — o painel (engine, cli, web, uplink_guard)

## ferramentas/ — utilitários situacionais
- `restaurar_backup.py` — volta o dongle ao firmware salvo
- `restaurar_calibracao_ssh.py` — restaura calibração do modem via SSH
- `fable_detector.py` — investiga o chip de um aparelho desconhecido (EDL)

## _legado/ — versão antiga arquivada (não usar; plano B)
- `instalar_portal.py` + `portal/` — o portal cativo antigo, substituído
  pelo painel em core/opendongle/. Mantido só como backup de segurança.
