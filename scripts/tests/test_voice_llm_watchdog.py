"""Tests para scripts/voice-llm-watchdog.py sin dependencias externas ni systemd."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

# Carga dinamica del script con path relativo a la raiz del repo:
SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "voice-llm-watchdog.py"
SPEC = importlib.util.spec_from_file_location("voice_llm_watchdog", SCRIPT_PATH)
watchdog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watchdog)


class TestVoiceLLMWatchdog(unittest.TestCase):
    def test_medir_tok_s_lee_predicted_per_second(self):
        fake_data = {
            "timings": {
                "predicted_per_second": 67.35,
            }
        }
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps(fake_data).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        with patch("urllib.request.urlopen", return_value=mock_resp):
            val = watchdog.medir_tok_s("http://127.0.0.1:8092", max_tokens=8)
            self.assertEqual(val, 67.35)

    def test_medir_tok_s_devuelve_none_si_falla(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError(ConnectionRefusedError())):
            val = watchdog.medir_tok_s("http://127.0.0.1:8092", max_tokens=8)
            self.assertIsNone(val)

    def test_decidir_sano(self):
        res = watchdog.decidir([70.0, 66.0], umbral=15.0, intentos=2)
        self.assertEqual(res, "sano")

    def test_decidir_degradado_necesita_dos_seguidas(self):
        self.assertEqual(watchdog.decidir([2.9, 70.0], umbral=15.0, intentos=2), "indeterminado")
        self.assertEqual(watchdog.decidir([2.9, 2.7], umbral=15.0, intentos=2), "degradado")

    def test_decidir_cuenta_none_como_degradado(self):
        self.assertEqual(watchdog.decidir([None, None], umbral=15.0, intentos=2), "degradado")

    def test_main_sano_no_reinicia(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            estado_path = Path(tmp_dir) / "estado.json"
            reparar_spy = MagicMock()
            rc = watchdog.main(
                argv=["--estado", str(estado_path)],
                medir=lambda url, max_tokens: 70.0,
                reparar=reparar_spy,
                dormir=lambda s: None,
            )
            self.assertEqual(rc, 0)
            reparar_spy.assert_not_called()

    def test_main_degradado_reinicia_una_vez(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            estado_path = Path(tmp_dir) / "estado.json"
            reparar_spy = MagicMock(return_value=True)
            with self.assertLogs("vigilante-voice-llm", level="ERROR") as cm:
                rc = watchdog.main(
                    argv=["--estado", str(estado_path)],
                    medir=lambda url, max_tokens: 2.9,
                    reparar=reparar_spy,
                    dormir=lambda s: None,
                )
            self.assertEqual(rc, 3)
            reparar_spy.assert_called_once()
            self.assertTrue(any("degradado" in line for line in cm.output))

    def test_main_respeta_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            estado_path = Path(tmp_dir) / "estado.json"
            watchdog.escribir_estado(estado_path, {"ultimo_reinicio": 1000.0})
            reparar_spy = MagicMock()
            with self.assertLogs("vigilante-voice-llm", level="ERROR") as cm:
                rc = watchdog.main(
                    argv=["--estado", str(estado_path), "--cooldown-s", "600"],
                    medir=lambda url, max_tokens: 2.9,
                    reparar=reparar_spy,
                    reloj=lambda: 1100.0,
                    dormir=lambda s: None,
                )
            self.assertEqual(rc, 6)
            reparar_spy.assert_not_called()
            self.assertEqual(len(cm.output), 1)
            self.assertIn("degradado", cm.output[0])

    def test_main_falla_de_reinicio(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            estado_path = Path(tmp_dir) / "estado.json"
            reparar_spy = MagicMock(return_value=False)
            rc = watchdog.main(
                argv=["--estado", str(estado_path)],
                medir=lambda url, max_tokens: 2.9,
                reparar=reparar_spy,
                dormir=lambda s: None,
            )
            self.assertEqual(rc, 4)
            reparar_spy.assert_called_once()

    def test_estado_es_atomico(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            estado_path = Path(tmp_dir) / "estado.json"
            data = {"ultimo_reinicio": 1729774000.5, "unit": "kateto-voice-llm.service"}
            watchdog.escribir_estado(estado_path, data)
            leido = watchdog.leer_estado(estado_path)
            self.assertEqual(leido, data)


if __name__ == "__main__":
    unittest.main()
