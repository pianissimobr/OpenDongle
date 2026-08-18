#!/bin/bash
# usb-role-autosense.sh
#   1) grupos de acesso pro 'user'
#   2) Bluetooth sempre ativo
#   3) LEDs liberados pro grupo 'leds' (nao existe pronto na imagem)
#   4) portas AT/QMI do modem liberadas pro grupo 'dialout', em qualquer papel
#   5) papel USB: PC -> DEVICE (RNDIS mgmt); senao -> HOST
#   6) em HOST: conexao 4G plug-and-play (le operadora do SIM -> APN)
set -u

ROLE_SW=/sys/class/usb_role/ci_hdrc.0-role-switch/role
UDC_STATE=/sys/class/udc/ci_hdrc.0/state
USB0_CARRIER=/sys/class/net/usb0/carrier
QMI_DEV=/dev/wwan0qmi0
AT_DEV=/dev/wwan0at0
APN_CONF=/etc/usb-role-autosense-apn.conf
USERNAME="user"
LEDS="red:power green:wlan blue:wan"
# "leds" nao e' grupo padrao da imagem (diferente de audio/video/dialout/
# disk...); criamos ele mesmo logo abaixo, antes do loop que atribui os
# grupos, pra ja entrar na lista como qualquer outro.
GROUPS_LIST="audio video dialout plugdev netdev input tty render lp bluetooth disk davfs users leds"
WAIT=${USB_SENSE_WAIT:-6}
PGW_IF="wwan0"
LOG=/var/log/usb-role-autosense.log

# dependencias necessarias (bluez=BT, libqmi-utils=4G, iw=wifi mon/diag)
DEPS="bluez libqmi-utils iw"
INSTALL_DEPS="${USB_INSTALL_DEPS:-1}"    # 0 desativa auto-instalacao

log(){ printf '%s %s\n' "$(date '+%F %T')" "$*" >>"$LOG" 2>/dev/null || true; }

# instalacao plug-and-play das dependencias (so instala se faltar; precisa internet na 1a vez)
ensure_deps() {
    command -v apt-get >/dev/null 2>&1 || { log "deps: apt-get ausente"; return 1; }
    local miss=0 p
    for p in $DEPS; do
        if ! dpkg -s "$p" >/dev/null 2>&1; then log "deps: pacote '$p' ausente"; miss=1; fi
    done
    [ "$miss" -eq 0 ] && { log "deps: ja presentes"; return 0; }
    [ "$INSTALL_DEPS" = "1" ] || { log "deps: auto-instalacao desativada (USB_INSTALL_DEPS=0)"; return 0; }
    log "deps: instalando [$DEPS] (precisa internet)"
    if env DEBIAN_FRONTEND=noninteractive apt-get update >/dev/null 2>&1; then
        if env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $DEPS \
             -o Dpkg::Options::=--force-confold -o Dpkg::Options::=--force-confdef >/dev/null 2>&1; then
            log "deps: instalados com sucesso [$DEPS]"
        else
            log "deps: FALHA no apt-get install [$DEPS]"
        fi
    else
        log "deps: apt-get update falhou (sem internet agora; rodar novamente quando houver)"
    fi
}

# ---- banco de APNs (MCC-MNC brasileiros). Edite no /etc/usb-role-autosense-apn.conf
# formato: "mcc-mnc apn" - chave em formato "c<nome>" ou numero
# Aqui usamos assoc. simples por nome de operadora via MCC-MNC
declare -A APN_MAP=(
  # Vivo
  ["724-01"]="zap.vivo.com.br"
  ["724-06"]="zap.vivo.com.br"
  ["724-10"]="zap.vivo.com.br"
  ["724-11"]="zap.vivo.com.br"
  ["724-23"]="zap.vivo.com.br"
  # TIM
  ["724-02"]="tim.com.br"
  ["724-04"]="tim.com.br"
  # Claro
  ["724-03"]="claro.com.br"
  ["724-05"]="claro.com.br"
  ["724-38"]="claro.com.br"
  # Oi
  ["724-16"]="gprs.oi.com.br"
  ["724-31"]="gprs.oi.com.br"
)
[ -f "$APN_CONF" ] && . "$APN_CONF"  # sobrepoe/estende via arquivo de config

[ -e "$ROLE_SW" ] || { log "role-switch ausente"; exit 1; }

# prova as dependencias (instala se faltar)
ensure_deps

# grupo "leds": nao vem pronto na imagem (diferente de audio/video/disk/
# etc.), entao criamos aqui, ANTES do loop de grupos, pra ele poder
# entrar no GROUPS_LIST como qualquer outro.
getent group leds >/dev/null 2>&1 || { groupadd -r leds 2>/dev/null && log "grupo 'leds' criado"; }

# ---------- (A) grupos ----------
if getent passwd "$USERNAME" >/dev/null; then
    for g in $GROUPS_LIST; do
        if getent group "$g" >/dev/null && ! id -nG "$USERNAME" | tr ' ' '\n' | grep -qx "$g"; then
            usermod -aG "$g" "$USERNAME" && log "usermod: +pgrp $g ($USERNAME)"
        fi
    done
    log "groups($USERNAME)="$(id -nG "$USERNAME")
fi

# ---------- (B) Bluetooth ----------
rfkill unblock bluetooth 2>/dev/null
if command -v hciconfig >/dev/null 2>&1; then
    hciconfig hci0 up 2>/dev/null && log "bluetooth hci0 UP" || log "bluetooth hci0: falha"
else
    log "bluez/hciconfig ausente"
fi

# ---------- (C) LEDs pro grupo 'leds', sem sudo ----------
# so brightness/trigger: sao fixos, sempre existem. delay_on/delay_off
# (do trigger "timer") sao criados pelo kernel na hora que o trigger muda
# pra "timer" -- nao da pra fixar permissao de boot pra algo que ainda
# nao existe nesse momento, entao esses dois continuam so-root.
for led in $LEDS; do
    d="/sys/class/leds/$led"
    [ -d "$d" ] || continue
    chgrp leds "$d/brightness" "$d/trigger" 2>/dev/null
    chmod 664 "$d/brightness" "$d/trigger" 2>/dev/null
done
log "LEDs liberados pro grupo 'leds' (brightness/trigger; delay_on/off continuam so-root)"

# ---------- (D) modem AT/QMI liberado pro grupo 'dialout', em qualquer papel ----------
# antes, isso so' rodava dentro do setup_4g() (so' em modo HOST). O
# usuario pode querer ler/mandar AT manualmente mesmo em modo DEVICE.
i=0
while [ ! -e "$AT_DEV" ] && [ "$i" -lt 15 ]; do /bin/sleep 1; i=$((i+1)); done
if [ -e "$AT_DEV" ] || [ -e "$QMI_DEV" ]; then
    chgrp dialout "$AT_DEV" "$QMI_DEV" 2>/dev/null
    chmod 660 "$AT_DEV" "$QMI_DEV" 2>/dev/null
    log "modem: portas AT/QMI liberadas pro grupo dialout"
else
    log "modem: portas AT/QMI nao apareceram em 15s (sem firmware mpss?)"
fi

# ---------- (E) papel USB ----------
usb_connected_to_pc() {
    [ "$(cat "$UDC_STATE" 2>/dev/null)" = "configured" ] && return 0
    [ "$(cat "$USB0_CARRIER" 2>/dev/null)" = "1" ] && return 0
    return 1
}
echo device > "$ROLE_SW"
deadline=$((SECONDS + WAIT))
while [ "$SECONDS" -lt "$deadline" ]; do
    usb_connected_to_pc && break
    /bin/sleep 0.5
done
ROLE="device"
if usb_connected_to_pc; then
    log "PC detectado -> DEVICE (RNDIS mgmt)"
else
    echo host > "$ROLE_SW"; ROLE="host"
    log "nenhum PC -> HOST"
fi

# ---------- (F) 4G plug-and-play ----------
# helper: envia comando AT e devolve a resposta (usando o AT port do modem)
at_resp() { # cmd tempo  (nunca travas: timeout interno no python + timeout externo)
    ATDEV="$AT_DEV" timeout 10 python3 - "$1" "$2" <<'PY'
import os,sys,time,tty,select,signal
cmd,waitt=sys.argv[1],float(sys.argv[2])
dev=os.environ["ATDEV"]
def _al(*_): sys.exit(0)
signal.signal(signal.SIGALRM, _al)
signal.alarm(int(waitt)+2)
try:
    fd=os.open(dev,os.O_RDWR); tty.setraw(fd)
except OSError:
    sys.exit(1)
try:
    time.sleep(0.2)
    try: os.read(fd,4096)
    except OSError: pass
    os.write(fd,(cmd+"\r").encode())
    buf=b""; end=time.time()+waitt
    while time.time()<end:
        r,_,_=select.select([fd],[],[],0.15)
        if r:
            try: d=os.read(fd,4096)
            except OSError: break
            if not d: break
            buf+=d
            if b"OK" in buf or b"ERROR" in buf: break
    sys.stdout.write(buf.decode(errors='replace'))
finally:
    os.close(fd)
PY
}

get_apn_from_sim() {
    # 1) IMSI do chip (AT+CIMI). Sem SIM -> ERROR.
    # MNC pode ter 2 ou 3 digitos (nao da pra saber so pelo IMSI sem tabela
    # oficial de MCC/MNC); tenta 2 digitos primeiro (caso do Brasil/724,
    # inclusive operadoras com MNC "01".."06") e cai pra 3 se nao achar.
    local imsi resp mcc mnc2 mnc3 key apn
    resp=$(at_resp "AT+CIMI" 4)
    imsi=$(echo "$resp" | grep -oE '[0-9]{15}' | head -1)
    [ -n "$imsi" ] || { log "4G: sem IMSI (sem SIM?)"; return 1; }

    mcc=${imsi:0:3}
    mnc2=${imsi:3:2}
    mnc3=${imsi:3:3}
    key="$mcc-$mnc2"
    apn="${APN_MAP[$key]-}"
    if [ -z "$apn" ]; then
        key="$mcc-$mnc3"
        apn="${APN_MAP[$key]-}"
    fi
    if [ -n "$apn" ]; then
        log "4G: SIM MCCMNC=$key (IMSI=$imsi) -> APN=$apn"
        APN="$apn"; return 0
    fi
    log "4G: operadora MCCMNC=$mcc-$mnc2 (ou $mcc-$mnc3) sem APN na tabela. Adicione '$mcc-$mnc2 apn' em $APN_CONF"
    return 1
}

setup_4g() {
    command -v qmicli >/dev/null 2>&1 || { log "4G: qmicli ausente"; return 1; }
    # chgrp/chmod das portas AT/QMI ja' rodou na secao (D), pra qualquer papel

    local i=0
    while [ ! -e "$QMI_DEV" ] && [ "$i" -lt 30 ]; do /bin/sleep 1; i=$((i+1)); done
    [ -e "$QMI_DEV" ] || { log "4G: $QMI_DEV nao apareceu"; return 1; }

    # habilita radio
    at_resp "AT+CFUN=1" 3 >/dev/null 2>&1

    # detecta APN a partir do SIM (se user nao forcar um)
    APN="${USB_4G_APN:-}"
    if [ -z "$APN" ]; then
        get_apn_from_sim || return 1
    else
        log "4G: APN forcado por env: $APN"
    fi
    [ -n "$APN" ] || return 1

    log "4G: conectando APN='$APN'"
    local net
    net=$(timeout 40 qmicli -d "$QMI_DEV" --wds-start-network="apn=$APN,ip-type=ipv4" --client-no-release-cid 2>&1)
    echo "$net" | grep -qi "Network started\|Packet data connection" || {
        log "4G: falha wds-start-network: $net"; return 1; }

    local cfg ip gw prefix
    cfg=$(timeout 25 qmicli -d "$QMI_DEV" --wds-get-current-settings 2>&1)
    ip=$(echo "$cfg" | awk '/ip./ {print $2}' | tr -d "'" | head -1)
    gw=$(echo "$cfg" | awk '/gateway/ {print $2}' | tr -d "'" | head -1)
    prefix=$(echo "$cfg" | awk '/prefix/ {print $2}' | tr -d "'" | head -1)
    [ -n "$prefix" ] || prefix="24"
    ip addr flush dev "$PGW_IF" 2>/dev/null
    if [ -n "$ip" ] && ip addr add "$ip/$prefix" dev "$PGW_IF" 2>/dev/null; then
        ip link set "$PGW_IF" up
        ip route replace default via "${gw:-$ip}" dev "$PGW_IF"
        log "4G: OK ip=$ip/$prefix gw=${gw:-$ip} dev=$PGW_IF"
    else
        log "4G: nao configurei wwan0 (cfg: $cfg)"
    fi
    return 0
}

if [ "$ROLE" = "host" ]; then
    setup_4g || log "4G: nao configurado (sem SIM/APN/tabela — esperado)"
else
    log "4G: papel DEVICE -> hotspot nao ativado"
fi
exit 0