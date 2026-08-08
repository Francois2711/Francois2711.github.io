#!/usr/bin/env python3
"""Check South African car marketplaces for Range Rover L322 (2007-2012)
listings and email new finds.

Reads/writes data/l322_seen.json to avoid repeat notifications.
"""
import json
import os
import re
import smtplib
import sys
from email.mime.text import MIMEText
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

SEEN_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "l322_seen.json")

SENDER = "francois2711@gmail.com"
RECIPIENT = "francois2711@gmail.com"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

YEAR_RE = re.compile(r"\b(200[7-9]|201[0-2])\b")
INCLUDE_RE = re.compile(r"range\s*rover", re.I)
EXCLUDE_RE = re.compile(
    r"sport|evoque|velar|discovery|defender|freelander|stormer", re.I
)
NAV_LINK_RE = re.compile(r"view more|show more|see all|see more|results?$", re.I)

SOURCES = [
    ("AutoTrader", "https://www.autotrader.co.za/cars-for-sale/land-rover/range-rover"),
    ("Cars.co.za", "https://www.cars.co.za/usedcars/Land-Rover/Range-Rover/"),
    ("Gumtree", "https://www.gumtree.co.za/s-cars-bakkies/land-rover~range-rover/v1c9077a2mamop1"),
    ("Junk Mail", "https://www.junkmail.co.za/cars/land-rover/range-rover/for-sale"),
]


COOKIE_BUTTON_TEXTS = ["Accept", "Accept All", "I Accept", "I agree", "Allow all", "Got it"]


def fetch_rendered_html(browser, url):
    page = browser.new_page(user_agent=USER_AGENT)
    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        for label in COOKIE_BUTTON_TEXTS:
            try:
                button = page.get_by_role("button", name=label, exact=False).first
                if button.is_visible(timeout=500):
                    button.click(timeout=500)
                    page.wait_for_timeout(500)
                    break
            except Exception:
                pass
        page.wait_for_timeout(1000)
        for _ in range(4):
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(800)
        return page.content()
    finally:
        page.close()


def find_candidates(browser, source_name, url):
    """Best-effort scrape of the JS-rendered page: a listing's year/model
    text usually lives in a sibling/child element of its <a>, not the
    anchor's own text, so match against each link plus a few ancestor
    levels (the enclosing listing "card")."""
    candidates = {}
    try:
        html = fetch_rendered_html(browser, url)
    except Exception as exc:
        print(f"[{source_name}] fetch failed: {exc}", file=sys.stderr)
        return candidates

    soup = BeautifulSoup(html, "html.parser")
    all_links = soup.find_all("a", href=True)
    model_mentions = 0
    for a in all_links:
        own_text = a.get_text(" ", strip=True)
        if NAV_LINK_RE.search(own_text):
            continue
        context_parts = [own_text, a.get("title", ""), a.get("aria-label", "")]
        node = a
        for _ in range(3):
            node = node.parent
            if node is None or node.name in ("body", "html", "[document]"):
                break
            context_parts.append(node.get_text(" ", strip=True))
        text = " ".join(filter(None, context_parts))
        if not text:
            continue
        if INCLUDE_RE.search(text):
            model_mentions += 1
        if INCLUDE_RE.search(text) and YEAR_RE.search(text) and not EXCLUDE_RE.search(text):
            full_url = urljoin(url, a["href"])
            snippet = a.get_text(" ", strip=True) or text
            candidates[full_url] = f"[{source_name}] {snippet.strip()[:140]}"

    print(
        f"[{source_name}] {len(all_links)} link(s), {model_mentions} mention 'range rover', "
        f"{len(candidates)} candidate(s) found"
    )
    return candidates


def send_email(subject, body):
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if not app_password:
        print("GMAIL_APP_PASSWORD not set, skipping email", file=sys.stderr)
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SENDER
    msg["To"] = RECIPIENT
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(SENDER, app_password)
            server.sendmail(SENDER, [RECIPIENT], msg.as_string())
        print("Email sent.")
    except Exception as exc:
        print(f"Failed to send email: {exc}", file=sys.stderr)


def load_seen():
    try:
        with open(SEEN_PATH) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_seen(seen):
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    with open(SEEN_PATH, "w") as f:
        json.dump(sorted(seen), f, indent=2)
        f.write("\n")


def main():
    seen = load_seen()

    all_candidates = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for name, url in SOURCES:
                all_candidates.update(find_candidates(browser, name, url))
        finally:
            browser.close()

    new_links = {url: label for url, label in all_candidates.items() if url not in seen}

    if new_links:
        lines = [f"{label}\n  {url}" for url, label in new_links.items()]
        body = (
            "New Range Rover L322 (2007-2012) listing(s) found in South Africa:\n\n"
            + "\n\n".join(lines)
        )
        print(body)
        send_email(f"{len(new_links)} new Range Rover L322 listing(s) found", body)
    else:
        print("No new listings found.")

    save_seen(seen | set(all_candidates.keys()))


if __name__ == "__main__":
    main()
