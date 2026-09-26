from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from parser.normalizer import normalize_email, normalize_phone, unique_sorted


PHONE_RE = re.compile(r"(?<!\d)(?:\+?7|8)[\s(.-]*\d{3}[\s).-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)")
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
CLINIC_WORDS = (
    "клиника",
    "медицинский центр",
    "медцентр",
    "стоматолог",
    "психологи",
    "психологический центр",
    "медицинская помощь",
    "врач",
    "лечение",
)
CONTACT_HINTS = (
    "контакт",
    "о нас",
    "адрес",
    "contact",
    "contacts",
    "about",
)
PERSONAL_SECTION_HINTS = re.compile(r"doctor|staff|team|employee|person|врач|доктор|сотрудник|команд", re.I)


@dataclass(slots=True)
class ExtractedContacts:
    phones: tuple[str, ...] = ()
    emails: tuple[str, ...] = ()
    telegram: tuple[str, ...] = ()
    whatsapp: tuple[str, ...] = ()
    vk: tuple[str, ...] = ()
    address: str = ""


def _clean_url(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))


def extract_contacts(html: str, base_url: str) -> ExtractedContacts:
    soup = BeautifulSoup(html, "html.parser")
    address = extract_address(soup)
    for node in soup(["script", "style", "noscript", "template"]):
        node.decompose()

    phones: list[str] = []
    emails: list[str] = []
    telegram: list[str] = []
    whatsapp: list[str] = []
    vk: list[str] = []

    for link in soup.find_all("a", href=True):
        if _inside_personal_section(link):
            continue
        href = str(link.get("href", "")).strip()
        lower = href.lower()
        if lower.startswith("tel:"):
            phone = normalize_phone(href[4:].split("?", 1)[0])
            if phone:
                phones.append(phone)
        elif lower.startswith("mailto:"):
            email = normalize_email(href[7:].split("?", 1)[0])
            if email:
                emails.append(email)

        absolute = _clean_url(urljoin(base_url, href))
        host = (urlsplit(absolute).hostname or "").lower()
        if host in {"t.me", "telegram.me"}:
            telegram.append(absolute)
        elif host in {"wa.me", "api.whatsapp.com", "whatsapp.com", "www.whatsapp.com"}:
            whatsapp.append(absolute)
        elif host == "vk.com" or host.endswith(".vk.com"):
            vk.append(absolute)

    text_soup = BeautifulSoup(str(soup), "html.parser")
    for node in text_soup.find_all(attrs={"class": PERSONAL_SECTION_HINTS}):
        node.decompose()
    for node in text_soup.find_all(attrs={"id": PERSONAL_SECTION_HINTS}):
        node.decompose()
    visible_text = text_soup.get_text(" ", strip=True)
    for match in PHONE_RE.findall(visible_text):
        phone = normalize_phone(match)
        if phone:
            phones.append(phone)
    for match in EMAIL_RE.findall(visible_text):
        email = normalize_email(match)
        if email:
            emails.append(email)

    return ExtractedContacts(
        phones=unique_sorted(phones),
        emails=unique_sorted(emails),
        telegram=unique_sorted(telegram),
        whatsapp=unique_sorted(whatsapp),
        vk=unique_sorted(vk),
        address=address,
    )


def _inside_personal_section(node) -> bool:
    for parent in node.parents:
        classes = " ".join(parent.get("class", [])) if parent.get("class") else ""
        marker = f"{parent.get('id', '')} {classes}"
        if PERSONAL_SECTION_HINTS.search(marker):
            return True
    return False


def extract_address(soup: BeautifulSoup) -> str:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                continue
            address = item.get("address")
            if isinstance(address, str) and len(address.strip()) >= 8:
                return _clean_text(address)
            if isinstance(address, dict):
                parts = [
                    address.get("postalCode"),
                    address.get("addressLocality"),
                    address.get("streetAddress"),
                ]
                value = ", ".join(str(part).strip() for part in parts if part)
                if len(value) >= 8:
                    return value

    address_node = soup.find("address")
    if address_node:
        value = _clean_text(address_node.get_text(" ", strip=True))
        if 8 <= len(value) <= 300:
            return value

    address_hint = re.compile(r"address|addr|contact-address|адрес", re.I)
    for node in soup.find_all(attrs={"class": address_hint}) + soup.find_all(attrs={"id": address_hint}):
        value = _clean_text(node.get_text(" ", strip=True))
        if 8 <= len(value) <= 300:
            return value
    return ""


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" \n\t,;")


def clinic_name(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for attrs in (
        {"property": "og:site_name"},
        {"name": "application-name"},
    ):
        node = soup.find("meta", attrs=attrs)
        if node and node.get("content"):
            return _clean_text(str(node["content"]))[:200]
    h1 = soup.find("h1")
    if h1:
        value = _clean_text(h1.get_text(" ", strip=True))
        if value:
            return value[:200]
    if soup.title and soup.title.string:
        value = re.split(r"[|—–]", soup.title.string, maxsplit=1)[0]
        return _clean_text(value)[:200]
    return ""


def is_probably_clinic(html: str, url: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    selected: list[str] = [url]
    if soup.title:
        selected.append(soup.title.get_text(" ", strip=True))
    for attrs in ({"name": "description"}, {"property": "og:description"}):
        node = soup.find("meta", attrs=attrs)
        if node and node.get("content"):
            selected.append(str(node["content"]))
    selected.extend(node.get_text(" ", strip=True) for node in soup.find_all("h1", limit=3))
    main = soup.find("main") or soup.body
    if main:
        selected.append(main.get_text(" ", strip=True)[:5000])
    haystack = " ".join(selected).lower()
    return any(word in haystack for word in CLINIC_WORDS)


def contact_page_links(html: str, base_url: str, domain: str, limit: int = 4) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        href = urljoin(base_url, str(link["href"]))
        parts = urlsplit(href)
        host = (parts.hostname or "").lower().removeprefix("www.")
        if host != domain or parts.scheme not in {"http", "https"}:
            continue
        clean = urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))
        if clean in seen:
            continue
        label = f"{link.get_text(' ', strip=True)} {parts.path}".lower()
        score = sum(2 for hint in CONTACT_HINTS if hint in label)
        if score:
            seen.add(clean)
            candidates.append((score, clean))
    candidates.sort(key=lambda item: (-item[0], len(item[1])))
    return [url for _, url in candidates[:limit]]
