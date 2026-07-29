#!/bin/bash
# install.sh — Instala as dependências do OpenStick Auto-Installer
# Testado em Ubuntu 22.04+ / Debian 12+. Rodar com sudo.
set -e

if [ "$EUID" -ne 0 ]; then
  echo "Rode com sudo: sudo ./install.sh"; exit 1
fi

echo "== Pacotes do sistema =="
apt update
apt install -y python3 python3-pip python3-venv git fastboot adb \
               android-sdk-libsparse-utils usbutils libusb-1.0-0 unzip

echo "== EDL (bkerler/edl) =="
if ! command -v edl >/dev/null 2>&1; then
  TMP=$(mktemp -d)
  git clone --depth 1 https://github.com/bkerler/edl.git "$TMP/edl"
  cd "$TMP/edl"
  # --break-system-packages: necessário em Debian/Ubuntu recentes (PEP 668)
  pip3 install --break-system-packages .
  # Regras udev para acesso ao dispositivo em modo EDL (05c6:9008) sem root
  cp Drivers/51-edl.rules /etc/udev/rules.d/ 2>/dev/null || true
  cp Drivers/50-android.rules /etc/udev/rules.d/ 2>/dev/null || true
  udevadm control --reload-rules && udevadm trigger || true
  cd /; rm -rf "$TMP"
else
  echo "edl já instalado."
fi

# Desativa o ModemManager durante o uso (ele "sequestra" a porta do dongle)
echo "== Aviso: ModemManager pode interferir no EDL =="
echo "   Se tiver problemas, rode: sudo systemctl stop ModemManager"

echo
echo "Pronto! Agora rode:  python3 setup_estrutura.py"
