"""Qual backup é de qual dongle — pelo hardware, não por sec/fsg.

Na bancada (2026-10), restaurações que pegavam "o backup mais recente"
copiaram sec, fsg e modemst entre aparelhos: dois dongles ficaram com sec/fsg
idênticos e um deles com IMEI zerado. sec/fsg deixaram de provar identidade.
Quem prova é o serial do chip (EDL, no gpt.txt) e o CID do eMMC.

Roda no PC:
    python3 -m pytest core/tests/test_identidade_backup.py -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import opendongle_autoinstall as ai  # noqa: E402

SEC, FSG = "a" * 64, "b" * 64
CID_A = "11010030303447453001a389e1f21200"
CID_B = "90014a48344732611102c79645b0c400"


def _gpt(serial):
    return ("Qualcomm Sahara / Firehose Client\n"
            f"Serial:            0x{serial}\n"
            "modemst1:            Offset 0x0000000008700000, Length 0x0000000000180000\n")


class _Pasta(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="ident-"))
        self._p = [mock.patch.object(ai, "BACKUP_DIR", self.base),
                   mock.patch.object(ai, "log", lambda *a, **k: None)]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def backup(self, nome, serial=None, cid=None, sec=SEC, fsg=FSG):
        pasta = self.base / nome
        pasta.mkdir()
        manifesto = {"arquivos": {"sec.bin": {"sha256": sec}, "fsg.bin": {"sha256": fsg}}}
        if cid:
            manifesto["emmc_cid"] = cid
        (pasta / "manifesto.json").write_text(json.dumps(manifesto))
        if serial:
            (pasta / "gpt.txt").write_text(_gpt(serial))
        return pasta


class TestSerialEdl(unittest.TestCase):
    def test_le_da_saida_do_edl(self):
        self.assertEqual(ai.serial_edl_do_texto(_gpt("0457D3CA")), "0457d3ca")
        self.assertIsNone(ai.serial_edl_do_texto("sem serial"))


class TestMesmaIdentidade(_Pasta):
    def test_clone_de_sec_fsg_nao_engana(self):
        """O caso real: mesmo sec/fsg, chips diferentes."""
        b = ai.identidade_backup(self.backup("dongle_1", serial="0457d3ca"))
        aparelho = {"serial_edl": "040cac4c", "sec": SEC, "fsg": FSG}
        self.assertIs(ai.mesma_identidade(b, aparelho), False)

    def test_serial_igual(self):
        b = ai.identidade_backup(self.backup("dongle_1", serial="0457d3ca"))
        self.assertIs(ai.mesma_identidade(b, {"serial_edl": "0457d3ca"}), True)

    def test_cid_igual(self):
        b = ai.identidade_backup(self.backup("dongle_1", cid=CID_A))
        self.assertIs(ai.mesma_identidade(b, {"emmc_cid": CID_A}), True)
        self.assertIs(ai.mesma_identidade(b, {"emmc_cid": CID_B}), False)

    def test_sem_hardware_em_comum_nao_decide(self):
        b = ai.identidade_backup(self.backup("dongle_1", serial="0457d3ca"))
        self.assertIsNone(ai.mesma_identidade(b, {"emmc_cid": CID_A}))

    def test_cid_do_info_json_do_backup_radio(self):
        pasta = self.backup("dongle_1")
        (pasta / "info.json").write_text(json.dumps({"emmc_cid": CID_A.upper()}))
        self.assertEqual(ai.identidade_backup(pasta)["emmc_cid"], CID_A)


class TestEscolherBackup(_Pasta):
    def test_escolhe_o_do_cid_mesmo_havendo_clone_mais_novo(self):
        self.backup("dongle_20260802", cid=CID_A)
        self.backup("dongle_20261001", cid=CID_B)          # mais novo, outro chip, mesmo sec/fsg
        escolhido = ai.escolher_backup(identidade={"emmc_cid": CID_A, "sec": SEC, "fsg": FSG})
        self.assertEqual(escolhido.name, "dongle_20260802")

    def test_backup_sem_hardware_nao_e_escolhido_sozinho(self):
        self.backup("dongle_antigo")
        with self.assertRaises(SystemExit) as e:
            ai.escolher_backup(identidade={"emmc_cid": CID_A, "sec": SEC, "fsg": FSG})
        self.assertIn("--pasta", str(e.exception))

    def test_pasta_explicita_sem_hardware_exige_sec_fsg(self):
        antigo = self.backup("dongle_antigo")
        self.assertEqual(ai.escolher_backup(str(antigo), {"emmc_cid": CID_A, "sec": SEC, "fsg": FSG}),
                         antigo)
        with self.assertRaises(SystemExit):
            ai.escolher_backup(str(antigo), {"emmc_cid": CID_A, "sec": "c" * 64, "fsg": FSG})

    def test_pasta_explicita_de_outro_chip_e_recusada(self):
        outro = self.backup("dongle_outro", serial="040cac4c")
        with self.assertRaises(SystemExit) as e:
            ai.escolher_backup(str(outro), {"serial_edl": "0457d3ca", "sec": SEC, "fsg": FSG})
        self.assertIn("OUTRO dongle", str(e.exception))

    def test_fastboot_com_dois_chips_exige_pasta(self):
        self.backup("dongle_1", serial="0457d3ca")
        self.backup("dongle_2", serial="040cac4c")       # mesmo sec/fsg
        with self.assertRaises(SystemExit):
            ai.escolher_backup()


class TestRegistrarCid(_Pasta):
    def test_liga_o_cid_ao_backup(self):
        pasta = self.backup("dongle_1", serial="0457d3ca")
        self.assertTrue(ai.registrar_cid(pasta, CID_A.upper()))
        self.assertEqual(ai.identidade_backup(pasta)["emmc_cid"], CID_A)

    def test_nao_troca_um_cid_ja_gravado(self):
        pasta = self.backup("dongle_1", cid=CID_A)
        self.assertFalse(ai.registrar_cid(pasta, CID_B))
        self.assertEqual(ai.identidade_backup(pasta)["emmc_cid"], CID_A)

    def test_cid_invalido_nao_grava(self):
        pasta = self.backup("dongle_1")
        self.assertFalse(ai.registrar_cid(pasta, "nao-e-cid"))


if __name__ == "__main__":
    unittest.main()
