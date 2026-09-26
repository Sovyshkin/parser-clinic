import unittest

from parser.contacts import contact_page_links, extract_contacts, is_probably_clinic


HTML = """
<html>
  <head><title>Стоматология Улыбка</title><meta name="description" content="Лечение зубов"></head>
  <body>
    <h1>Клиника Улыбка</h1>
    <a href="tel:8 (912) 345-67-89">Позвонить</a>
    <a href="mailto:INFO@EXAMPLE.RU">Почта</a>
    <a href="https://t.me/clinic_test">Telegram</a>
    <a href="https://wa.me/79123456789">WhatsApp</a>
    <a href="https://vk.com/clinic_test">VK</a>
    <address>Москва, ул. Примерная, 10</address>
    <a href="/contacts/">Контакты</a>
    <section class="doctors">
      <a href="tel:+7 999 111-22-33">Личный телефон врача</a>
    </section>
  </body>
</html>
"""


class ContactTests(unittest.TestCase):
    def test_extracts_public_business_contacts(self) -> None:
        contacts = extract_contacts(HTML, "https://example.ru/")
        self.assertEqual(contacts.phones, ("+79123456789",))
        self.assertEqual(contacts.emails, ("info@example.ru",))
        self.assertEqual(contacts.telegram, ("https://t.me/clinic_test",))
        self.assertEqual(contacts.address, "Москва, ул. Примерная, 10")

    def test_reads_schema_org_address_before_removing_scripts(self) -> None:
        html = """
        <script type="application/ld+json">
        {"@type":"MedicalClinic","address":{"postalCode":"101000","addressLocality":"Москва","streetAddress":"ул. Ленина, 1"}}
        </script>
        <h1>Медицинский центр</h1>
        """
        contacts = extract_contacts(html, "https://example.ru/")
        self.assertEqual(contacts.address, "101000, Москва, ул. Ленина, 1")

    def test_clinic_check_and_contact_links(self) -> None:
        self.assertTrue(is_probably_clinic(HTML, "https://example.ru/"))
        self.assertEqual(
            contact_page_links(HTML, "https://example.ru/", "example.ru"),
            ["https://example.ru/contacts/"],
        )


if __name__ == "__main__":
    unittest.main()
