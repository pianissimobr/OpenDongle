# backups-radio/

Backups das partições de rádio de cada dongle, separados pelo **IMEI da
etiqueta**. Só este LEIAME vai para o git: os binários guardam a calibração e a
identidade (IMEI) de cada aparelho e ficam fora de propósito.

```
backups-radio/
  <IMEI da etiqueta>/
    <data-hora>/          um por backup — nunca sobrescreve
      modemst1.bin modemst2.bin fsg.bin fsc.bin persist.bin modem.bin sec.bin
      SHA256SUMS
      info.json           IMEI da etiqueta e do modem, serial do SoC, CID do eMMC,
                          id do OpenDongle e o sha256 de cada partição
  _conjunto-B-origem-desconhecida/   ver ORIGEM.txt
```

## Fazer o backup (dongle que já roda Debian)

```
python3 ferramentas/backup_radio.py --imei 861766035241425 --usuario alan
```

- Faça **antes** de qualquer flash, reinstalação ou teste que mexa nas partições.
- O script avisa em vermelho se uma partição vier **só com zeros**: aquele
  aparelho já perdeu o que ela guardava, e o backup não devolve isso.
- Guarde a pasta **também fora deste PC** (HD externo, nuvem). Se o PC morrer
  junto com o dongle, o IMEI se perde.
- `--emmc-completa` copia também o eMMC inteiro (~3,9 GB): o backup mais
  completo que existe do aparelho.

## Por que isso importa

O IMEI e a calibração de rádio moram no `persist`, no `modemst1/2` e no `fsg`,
e são **únicos de cada aparelho**. Gravar o backup de outro dongle não devolve
o IMEI (ver `_conjunto-B-origem-desconhecida/ORIGEM.txt`). O dongle de teste
perdeu os dele num flash, sem backup, e ficou com IMEI `000000000000000`.
