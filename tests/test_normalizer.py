import unittest

from parser.normalizer import normalize_domain, normalize_email, normalize_phone, root_url


class NormalizerTests(unittest.TestCase):
    def test_domain_normalization(self) -> None:
        self.assertEqual(normalize_domain("HTTPS://WWW.Clinic.RU/path/"), "clinic.ru")
        self.assertEqual(root_url("http://www.clinic.ru/path?q=1"), "http://clinic.ru/")

    def test_phone_normalization(self) -> None:
        self.assertEqual(normalize_phone("8 (912) 345-67-89"), "+79123456789")
        self.assertEqual(normalize_phone("+7 912 345 67 89"), "+79123456789")
        self.assertIsNone(normalize_phone("123"))

    def test_email_normalization(self) -> None:
        self.assertEqual(normalize_email(" INFO@Clinic.RU "), "info@clinic.ru")
        self.assertIsNone(normalize_email("not-an-email"))


if __name__ == "__main__":
    unittest.main()

