import unittest

from bot.handlers import parse_site_limit


class BotHelperTests(unittest.TestCase):
    def test_custom_site_limit(self) -> None:
        self.assertEqual(parse_site_limit(" 37 "), 37)
        self.assertEqual(parse_site_limit("1"), 1)
        self.assertEqual(parse_site_limit("100"), 100)
        self.assertEqual(parse_site_limit("200"), 200)
        self.assertIsNone(parse_site_limit("0"))
        self.assertIsNone(parse_site_limit("201"))
        self.assertIsNone(parse_site_limit("десять"))


if __name__ == "__main__":
    unittest.main()
