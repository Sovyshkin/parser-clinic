import os
import unittest
from pathlib import Path
from unittest.mock import patch

from config import Settings


class SettingsTests(unittest.TestCase):
    def test_multiple_admin_ids_and_legacy_value(self) -> None:
        env = {
            "ADMIN_TELEGRAM_IDS": "123, 456;789",
            "ADMIN_TELEGRAM_ID": "456",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings.from_env(Path("/dev/null"))
        self.assertEqual(settings.admin_telegram_ids, {123, 456, 789})


if __name__ == "__main__":
    unittest.main()
