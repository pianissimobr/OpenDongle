"""Guarda térmica: o papel do thermal-engine do firmware original.

O que importa travar:
  - nível 1 (78°) só limita a CPU — não mexe no rádio nem na banda;
  - nível 2 (85°) desconecta e põe o rádio em baixo consumo;
  - a volta só acontece abaixo de 72°, depois de 2 leituras seguidas
    (folga, para não ficar ligando e desligando o rádio);
  - o vigia do 4G não reconecta enquanto a pausa durar.

Roda no PC:
    python3 -m pytest core/tests/test_guarda_termica.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE = Path(tempfile.mkdtemp(prefix="termico-"))
os.environ.update(OPENDONGLE_CONFIG=str(BASE / "config.json"),
                  OPENDONGLE_RUN=str(BASE / "run"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "opendongle"))

import opendongle_engine as eng  # noqa: E402


class GuardaTermica(unittest.TestCase):
    def setUp(self):
        eng._TERMICO.update(nivel=0, abaixo=0, log=0.0)
        self.temp = 60.0
        self.cpu, self.radio, self.desconectou = [], [], 0
        patches = [
            mock.patch.object(eng, "_temp_guarda",
                              lambda: (self.temp, {"modem-thermal": self.temp})),
            mock.patch.object(eng, "_cpu_teto", self.cpu.append),
            mock.patch.object(eng, "_radio_4g", self.radio.append),
            mock.patch.object(eng, "modem_desconectar", self._desconectar),
            mock.patch.object(eng, "TERMICO_JSON", str(BASE / "termico.json")),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _desconectar(self):
        self.desconectou += 1

    def leitura(self, temp):
        self.temp = temp
        return eng.guarda_termica()

    def test_normal_nao_faz_nada(self):
        self.assertEqual(self.leitura(70), [])
        self.assertEqual((self.cpu, self.radio, self.desconectou), ([], [], 0))

    def test_nivel_1_so_limita_a_cpu(self):
        self.leitura(79)
        self.assertEqual(eng.termico_nivel(), 1)
        self.assertEqual(self.cpu, [eng.TERMICO_CPU_KHZ[1]])
        self.assertEqual(self.radio, [])
        self.assertEqual(self.desconectou, 0)

    def test_nivel_2_pausa_o_radio(self):
        self.leitura(86)
        self.assertEqual(eng.termico_nivel(), 2)
        self.assertEqual(self.radio, [False])
        self.assertEqual(self.desconectou, 1)

    def test_volta_so_abaixo_da_folga_e_com_duas_leituras(self):
        self.leitura(86)
        self.leitura(75)                    # ainda acima de 72: segue em pausa
        self.assertEqual(eng.termico_nivel(), 2)
        self.leitura(70)                    # 1ª abaixo: ainda espera
        self.assertEqual(eng.termico_nivel(), 2)
        self.leitura(70)                    # 2ª abaixo: desce e religa o rádio
        self.assertEqual(eng.termico_nivel(), 1)
        self.assertEqual(self.radio, [False, True])

    def test_vigia_nao_reconecta_em_pausa(self):
        self.leitura(86)
        eng._VIGIA_4G.update(proxima=0.0, espera=30, sem_internet=5, ultimo=None)
        with mock.patch.object(eng, "modem_conectar") as conectar, \
                mock.patch.object(eng, "plugado_no_pc", return_value=False), \
                mock.patch.object(eng.conf, "carregar",
                                  return_value={"wan": {"ativo": True, "no_pc": False}}):
            self.assertIsNone(eng.vigiar_4g(False))
            conectar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
