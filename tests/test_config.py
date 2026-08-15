import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


CONFIG_PATH = Path(__file__).resolve().parents[1] / "app" / "config.py"


def load_config(module_name: str, env_file: Path, environ: dict[str, str]):
    spec = importlib.util.spec_from_file_location(module_name, CONFIG_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        os.environ,
        {"GZR_ENV_FILE": str(env_file), **environ},
        clear=True,
    ):
        spec.loader.exec_module(module)
    return module


class ConfigPersistenceTests(unittest.TestCase):
    def test_writes_ai_settings_only_to_configured_env_file(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            config = load_config(
                "isolated_app_config",
                env_file,
                {
                    "AI_API_KEY": "",
                    "AI_BASE_URL": "",
                    "AI_MODEL": "",
                    "DEEPSEEK_API_KEY": "",
                    "DEEPSEEK_BASE_URL": "",
                    "DEEPSEEK_MODEL": "",
                },
            )

            config.set_api_key("test-key")
            config.set_base_url("https://example.test/v1")
            config.set_model("test-model")

            self.assertEqual(config.KEY, "test-key")
            self.assertEqual(config.BASE_URL, "https://example.test/v1")
            self.assertEqual(config.MODEL, "test-model")
            self.assertEqual(
                env_file.read_text(encoding="utf-8").splitlines(),
                [
                    "AI_API_KEY=test-key",
                    "AI_BASE_URL=https://example.test/v1",
                    "AI_MODEL=test-model",
                ],
            )

    def test_uses_legacy_values_when_ai_variables_are_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "DEEPSEEK_API_KEY=legacy-key\n"
                "DEEPSEEK_BASE_URL=https://legacy.test\n"
                "DEEPSEEK_MODEL=legacy-model\n",
                encoding="utf-8",
            )
            config = load_config("legacy_app_config", env_file, {})

            self.assertEqual(config.KEY, "legacy-key")
            self.assertEqual(config.BASE_URL, "https://legacy.test")
            self.assertEqual(config.MODEL, "legacy-model")


if __name__ == "__main__":
    unittest.main()
