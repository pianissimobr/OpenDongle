"""O nome da rede do hotspot precisa ser único por dongle.

Dois dongles na mesma casa com o mesmo SSID "OpenDongle" fariam o celular
pular entre os dois sem o usuário saber qual é o dele. O padrão passa a ser
OpenDongle_<4 últimos hex do id> — o mesmo rótulo que a tela de boas-vindas
mostra, então o usuário casa os dois olhando o aparelho e a lista de redes.

A regra que importa: um nome que o USUÁRIO escolheu nunca é sobrescrito. Só
o marcador "@id@" (o estado de fábrica) vira OpenDongle_<id>.

Roda no PC:
    python3 -m pytest core/tests/test_ssid_unico.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE = Path(tempfile.mkdtemp(prefix="ssid-"))
ETC = BASE / "etc"
ETC.mkdir(parents=True, exist_ok=True)
ID_FILE = ETC / "id"

os.environ.update(
    OPENDONGLE_CONFIG=str(ETC / "config.json"),
    OPENDONGLE_RUN=str(BASE / "run"),
)
(Path(os.environ["OPENDONGLE_RUN"])).mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "opendongle"))

import opendongle_config as conf  # noqa: E402
import opendongle_engine as eng  # noqa: E402


def _config_com(ssid: str) -> dict:
    cfg = json.loads(json.dumps(conf.PADRAO))
    cfg["wifi"]["hotspot"]["ssid"] = ssid
    return cfg


class _IdPatchMixin:
    """Aponta o caminho do id para o arquivo de teste. O motor e o módulo de
    config cada um têm a sua constante ID_APARELHO (config não importa o
    motor para não criar ciclo), então é preciso trocar nos dois."""

    def _apontar_id(self):
        patches = [mock.patch.object(eng, "ID_APARELHO", str(ID_FILE)),
                   mock.patch.object(conf, "ID_APARELHO", str(ID_FILE))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


class TestRotuloESsidPadrao(_IdPatchMixin, unittest.TestCase):
    """rotulo_dongle() e ssid_padrao(): os 4 últimos hex do id, em maiúscula."""

    def setUp(self):
        self._apontar_id()

    def test_rotulo_sao_quatro_hex_maiusculos(self):
        ID_FILE.write_text("a3f7b2c1d4e5f6a7\n")
        self.assertEqual(eng.rotulo_dongle(), "6A7" if False else "F6A7")

    def test_ssid_tem_o_formato_certo(self):
        ID_FILE.write_text("a3f7b2c1d4e5f6a7\n")
        self.assertEqual(eng.ssid_padrao(), "OpenDongle_F6A7")

    def test_dois_dongles_da_rede_da_saids_diferentes(self):
        """O ponto do desenho: mesmo de fábrica, dois dongles não colidem."""
        ID_FILE.write_text("aaaaaaaaaaaaaa01\n")
        a = eng.ssid_padrao()
        ID_FILE.write_text("aaaaaaaaaaaaaa02\n")
        b = eng.ssid_padrao()
        self.assertNotEqual(a, b)

    def test_nome_da_base_preservado(self):
        ID_FILE.write_text("0123456789abcdef\n")
        self.assertTrue(eng.ssid_padrao().startswith("OpenDongle_"))

    def test_cabe_no_limite_de_32_bytes(self):
        """O 802.11 limita o SSID a 32 bytes: OpenDongle_XXXX fica em 16."""
        ID_FILE.write_text("0123456789abcdef\n")
        self.assertLessEqual(len(eng.ssid_padrao().encode()), 32)


class TestMarcadorSubstituido(_IdPatchMixin, unittest.TestCase):
    """_ssid_unico(): só age enquanto o nome for o marcador de fábrica."""

    def setUp(self):
        self._apontar_id()

    def test_marcador_vira_nome_do_dongle(self):
        ID_FILE.write_text("0123456789abcdef\n")
        cfg = _config_com(conf.SSID_A_GERAR)
        self.assertTrue(conf._ssid_unico(cfg))
        self.assertEqual(cfg["wifi"]["hotspot"]["ssid"], "OpenDongle_CDEF")

    def test_nome_do_usuario_e_respeitado(self):
        """Se a pessoa já escolheu um nome no painel, nada muda."""
        cfg = _config_com("Meu Dongle da Cozinha")
        self.assertFalse(conf._ssid_unico(cfg))
        self.assertEqual(cfg["wifi"]["hotspot"]["ssid"], "Meu Dongle da Cozinha")

    def test_nome_generado_anterior_e_respeitado(self):
        """Um SSID que JÁ tem o formato OpenDongle_XXXX também é do usuário
        (ele pode ter digitado à mão)."""
        ID_FILE.write_text("0123456789abcdef\n")
        cfg = _config_com("OpenDongle_9999")
        self.assertFalse(conf._ssid_unico(cfg))
        self.assertEqual(cfg["wifi"]["hotspot"]["ssid"], "OpenDongle_9999")

    def test_sem_id_usa_rotulo_neutro(self):
        """Ainda sem o arquivo de id (primeiro boot muito inicial): não
        quebra, usa um rótulo neutro em vez de falhar."""
        ID_FILE.unlink(missing_ok=True)
        cfg = _config_com(conf.SSID_A_GERAR)
        self.assertTrue(conf._ssid_unico(cfg))
        self.assertEqual(cfg["wifi"]["hotspot"]["ssid"], "OpenDongle_0000")

    def test_id_corrompido_usa_rotulo_neutro(self):
        ID_FILE.write_text("nao-e-um-id-valido\n")
        cfg = _config_com(conf.SSID_A_GERAR)
        self.assertTrue(conf._ssid_unico(cfg))
        self.assertEqual(cfg["wifi"]["hotspot"]["ssid"], "OpenDongle_0000")


class TestValidacaoAceitaOMarcador(unittest.TestCase):
    """validar() precisa aceitar o marcador, senão salvar() levanta."""

    def test_marcador_passa_na_validacao(self):
        cfg = _config_com(conf.SSID_A_GERAR)
        erros = [e for e in conf.validar(cfg) if "Hotspot" in e]
        self.assertEqual(erros, [], f"marcador rejeitado: {erros}")

    def test_nome_invalido_ainda_reprovado(self):
        cfg = _config_com("")
        erros = [e for e in conf.validar(cfg) if "Hotspot" in e]
        self.assertTrue(erros)

    def test_nome_valido_aceito(self):
        cfg = _config_com("Minha Rede")
        erros = [e for e in conf.validar(cfg) if "Hotspot" in e]
        self.assertEqual(erros, [])


class TestPrimeiroCarregamento(_IdPatchMixin, unittest.TestCase):
    """carregar() num dongle sem config: nasce já com o nome único."""

    def setUp(self):
        self._apontar_id()
        # cada teste usa seu próprio arquivo: config() mescla o arquivo com o
        # PADRAO e o salvo de um teste contaminaria o seguinte
        self.cfg_path = ETC / f"config-{self._testMethodName}.json"
        self._patch_cfg = mock.patch.object(conf, "CONFIG", str(self.cfg_path))
        self._patch_cfg.start()
        self.addCleanup(self._patch_cfg.stop)

    def test_config_inexistente_ganha_o_nome(self):
        ID_FILE.write_text("deadbeefdeadbeef\n")
        self.cfg_path.unlink(missing_ok=True)
        with mock.patch.object(conf, "salvar"):
            cfg = conf.carregar()
        self.assertEqual(cfg["wifi"]["hotspot"]["ssid"], "OpenDongle_BEEF")

    def test_config_existente_com_marcador_e_corrigido(self):
        """Arquivo já tem o marcador dentro (instalação anterior): o load
        troca em memória e tenta gravar."""
        ID_FILE.write_text("deadbeefdeadbeef\n")
        self.cfg_path.write_text(json.dumps(_config_com(conf.SSID_A_GERAR)))
        with mock.patch.object(conf, "salvar"):
            cfg = conf.carregar()
        self.assertEqual(cfg["wifi"]["hotspot"]["ssid"], "OpenDongle_BEEF")

    def test_config_existente_com_nome_do_usuario_intacto(self):
        ID_FILE.write_text("deadbeefdeadbeef\n")
        self.cfg_path.write_text(json.dumps(_config_com("Rede da Vovó")))
        with mock.patch.object(conf, "salvar") as salvar:
            cfg = conf.carregar()
        self.assertEqual(cfg["wifi"]["hotspot"]["ssid"], "Rede da Vovó")
        salvar.assert_not_called()


class TestCliSsidPadrao(unittest.TestCase):
    """`opendongle_cli.py ssid-padrao` imprime o nome, sem mexer em nada."""

    def test_imprime_o_nome(self):
        import subprocess
        cli = Path(__file__).resolve().parents[1] / "opendongle" / "opendongle_cli.py"
        ID_FILE.write_text("0123456789abcdef\n")
        # o subprocesso importa os módulos do painel, que vários tocam
        # /etc/opendongle no import — aponta todos para o temporário
        env = dict(os.environ,
                   OPENDONGLE_ID_ARQUIVO=str(ID_FILE),
                   OPENDONGLE_CONFIG=str(ETC / "config.json"),
                   OPENDONGLE_RUN=str(BASE / "run"))
        r = subprocess.run([sys.executable, str(cli), "ssid-padrao"],
                           capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "OpenDongle_CDEF")


if __name__ == "__main__":
    unittest.main()

class TestSsidDeFabrica(unittest.TestCase):
    """O SSID de fábrica da imagem NÃO é escolha do dono.

    Regressão do P-5: migrar_estado_atual() adotava o '4G-UFI-XX' que a
    imagem OpenStick já trazia, achando que era nome escolhido. O
    marcador @id@ ficava fora do config, _ssid_unico() nunca rodava e o
    painel continuava anunciando OpenDongle_<4 hex> para uma rede que o
    dongle não tinha.
    """

    def _migra_com(self, nm):
        with mock.patch.object(conf, "NM_HOTSPOT", "/dev/null"), \
             mock.patch.object(conf, "_ler_ini_nm", return_value=nm):
            return conf.migrar_estado_atual()

    def test_ssid_de_fabrica_vira_marcador(self):
        cfg = self._migra_com({"ssid": "4G-UFI-XX", "psk": "1234567890"})
        self.assertEqual(cfg["wifi"]["hotspot"]["ssid"], conf.SSID_A_GERAR)

    def test_senha_de_fabrica_vira_padrao(self):
        cfg = self._migra_com({"ssid": "4G-UFI-XX", "psk": "1234567890"})
        self.assertEqual(cfg["wifi"]["hotspot"]["senha"],
                         conf.PADRAO["wifi"]["hotspot"]["senha"])

    def test_nome_escolhido_por_alguem_e_preservado(self):
        """Se alguém trocou, continua com o nome dele — essa é a regra que
        o P-5 promete."""
        cfg = self._migra_com({"ssid": "CasaDaVovo", "psk": "minhasenha123"})
        self.assertEqual(cfg["wifi"]["hotspot"]["ssid"], "CasaDaVovo")
        self.assertEqual(cfg["wifi"]["hotspot"]["senha"], "minhasenha123")

    def test_depois_da_migracao_o_ssid_vira_unico(self):
        """Fim a fim: o que a tela anuncia é o que o dongle vai usar."""
        cfg = self._migra_com({"ssid": "4G-UFI-XX", "psk": "1234567890"})
        self.assertTrue(conf._ssid_unico(cfg))
        self.assertRegex(cfg["wifi"]["hotspot"]["ssid"],
                         r"^OpenDongle_[0-9A-F]{4}$")


class TestResetAnunciaONomeCerto(_IdPatchMixin, unittest.TestCase):
    """Depois do reset de fábrica, o aviso tem que dizer a rede que vai
    mesmo existir — não 'OpenDongle' fixo.

    O reset devolve o config ao marcador '@id@', que vira
    OpenDongle_<4 hex>. O aviso antigo usava uma constante literal
    'OpenDongle' e mandava o cliente procurar uma rede que não existe.
    """

    def setUp(self):
        self._apontar_id()

    def test_aviso_do_reset_nao_promete_rede_inexistente(self):
        with mock.patch.object(eng.aplic, "aplicar",
                               return_value={"ok": True}), \
             mock.patch.object(eng, "ssid_padrao", return_value="OpenDongle_7B3A"):
            aviso = eng.reset()["aviso"]
        self.assertIn("OpenDongle_7B3A", aviso)
        self.assertNotIn("Wi-Fi: OpenDongle ", aviso)

    def test_nome_prometido_bate_com_o_do_dongle(self):
        """O que o aviso promete é o que ssid_padrao() devolve."""
        with mock.patch.object(eng.aplic, "aplicar",
                               return_value={"ok": True}):
            aviso = eng.reset()["aviso"]
        self.assertIn(eng.ssid_padrao(), aviso)


class TestPerfilNMNaoMente(unittest.TestCase):
    """O .nmconnection não pode ficar com valor que não existe mais.

    Depois da migração para o systemd-networkd quem manda no hotspot é o
    hostapd. O perfil do NM continua no disco com o SSID de fábrica e tem
    cara de configuração de rede — quem lê, chega errado.
    """

    def setUp(self):
        self.arq = Path(tempfile.mkdtemp()) / "hotspot.nmconnection"
        self.arq.write_text(
            "[connection]\nid=hotspot\ntype=wifi\n\n"
            "[wifi]\nssid=4G-UFI-XX\nmode=ap\n\n"
            "[wifi-security]\nkey-mgmt=wpa-psk\npsk=1234567890\n")

    def test_reescreve_ssid_e_psk(self):
        with mock.patch.object(conf, "NM_HOTSPOT", str(self.arq)):
            self.assertTrue(conf.sincronizar_perfil_nm("OpenDongle_2A24", "opendongle"))
        txt = self.arq.read_text()
        self.assertIn("ssid=OpenDongle_2A24", txt)
        self.assertIn("psk=opendongle", txt)
        self.assertNotIn("4G-UFI-XX", txt)

    def test_preserva_o_resto_do_perfil(self):
        with mock.patch.object(conf, "NM_HOTSPOT", str(self.arq)):
            conf.sincronizar_perfil_nm("OpenDongle_2A24", "opendongle")
        txt = self.arq.read_text()
        for linha in ("id=hotspot", "type=wifi", "mode=ap", "key-mgmt=wpa-psk"):
            self.assertIn(linha, txt)

    def test_idempotente(self):
        with mock.patch.object(conf, "NM_HOTSPOT", str(self.arq)):
            conf.sincronizar_perfil_nm("OpenDongle_2A24", "opendongle")
            self.assertFalse(conf.sincronizar_perfil_nm("OpenDongle_2A24", "opendongle"))

    def test_arquivo_ausente_nao_e_criado(self):
        """Se o NM nunca esteve aqui, não inventar arquivo."""
        alvo = Path(tempfile.mkdtemp()) / "nao-existe.nmconnection"
        with mock.patch.object(conf, "NM_HOTSPOT", str(alvo)):
            self.assertFalse(conf.sincronizar_perfil_nm("OpenDongle_2A24", "opendongle"))
        self.assertFalse(alvo.exists())

    def test_perfil_0600(self):
        """A senha do hotspot fica no arquivo: permissão de keyfile do NM."""
        with mock.patch.object(conf, "NM_HOTSPOT", str(self.arq)):
            conf.sincronizar_perfil_nm("OpenDongle_2A24", "opendongle")
        self.assertEqual(oct(self.arq.stat().st_mode)[-3:], "600")
