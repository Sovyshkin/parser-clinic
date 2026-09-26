import unittest

from bot.keyboards import limit_menu, persistent_menu


class KeyboardTests(unittest.TestCase):
    def test_persistent_menu_button(self) -> None:
        keyboard = persistent_menu()
        self.assertTrue(keyboard.is_persistent)
        self.assertEqual(keyboard.keyboard[0][0].text, "☰ Меню")

    def test_limit_menu_contains_custom_and_200(self) -> None:
        labels = [button.text for row in limit_menu().inline_keyboard for button in row]
        self.assertIn("200", labels)
        self.assertIn("✏️ Своё количество", labels)


if __name__ == "__main__":
    unittest.main()
