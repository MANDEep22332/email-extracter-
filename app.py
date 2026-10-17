from collections import deque
import html
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request
import requests
import urllib3

# Suppress SSL certificate warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

IGNORED_EXTENSIONS = (
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".zip",
    ".tar",
    ".gz",
    ".rar",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".pptx",
    ".ppt",
    ".mp4",
    ".mp3",
    ".css",
    ".js",
)


def is_valid_internal(url: str, base_domain: str) -> bool:
    """Verifies that the URL belongs to the target domain or its subdomains."""
    parsed = urlparse(url)
    if parsed.scheme not in ["http", "https"]:
        return False

    clean_base = base_domain.lower().replace("www.", "")
    host = parsed.netloc.lower()
    return host == clean_base or host.endswith("." + clean_base)


def extract_emails(html_text: str) -> set[str]:
    """Extracts standard, obfuscated, and mailto links from page content."""
    decoded_html = html.unescape(html_text)
    found_emails = set()

    # Standard email format
    standard_pattern = r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"
    for email in re.findall(standard_pattern, decoded_html):
        if not any(
            email.lower().endswith(ext)
            for ext in [".png", ".jpg", ".jpeg", ".gif"]
        ):
            found_emails.add(email.lower())

    # Obfuscated formats: name [at] domain [dot] com
    obfuscated_pattern = (
        r"([a-zA-Z0-9._%+-]+)\s*(?:\[at\]|\(at\)|@)\s*([a-zA-Z0-9.-]+)\s*(?:\[dot\]|\(dot\)|\.)\s*([a-zA-Z]{2,})"
    )
    for user, domain_part, tld in re.findall(
        obfuscated_pattern, decoded_html, flags=re.IGNORECASE
    ):
        found_emails.add(f"{user}@{domain_part}.{tld}".lower())

    # mailto: links
    soup = BeautifulSoup(decoded_html, "html.parser")
    for link in soup.find_all("a", href=True):
        href = link["href"].strip()
        if href.lower().startswith("mailto:"):
            clean = href.split(":", 1)[1].split("?")[0].strip()
            if re.match(standard_pattern, clean):
                found_emails.add(clean.lower())

    return found_emails


def crawl_site(start_url: str, max_pages: int = 15) -> set[str]:
    """Crawl internal links starting from start_url up to max_pages."""
    parsed_start = urlparse(start_url)
    base_domain = parsed_start.netloc
    urls_to_visit = deque([start_url])
    visited_urls = set()
    all_emails = set()

    session = requests.Session()
    session.headers.update(HEADERS)

    while urls_to_visit and len(visited_urls) < max_pages:
        current_url = urls_to_visit.popleft()

        if current_url in visited_urls:
            continue

        visited_urls.add(current_url)

        try:
            resp = session.get(current_url, verify=False, timeout=6)
            content_type = resp.headers.get("Content-Type", "").lower()
            if resp.status_code != 200 or "text/html" not in content_type:
                continue

            all_emails.update(extract_emails(resp.text))

            soup = BeautifulSoup(resp.text, "html.parser")
            for a_tag in soup.find_all("a", href=True):
                full_url = urljoin(current_url, a_tag["href"]).split("#")[0]

                if any(
                    full_url.lower().endswith(ext) for ext in IGNORED_EXTENSIONS
                ):
                    continue

                if (
                    is_valid_internal(full_url, base_domain)
                    and full_url not in visited_urls
                    and full_url not in urls_to_visit
                ):
                    urls_to_visit.append(full_url)

        except requests.exceptions.RequestException:
            continue

    return all_emails


# Web Routes
@app.route("/")
def index():
    """Serves the frontend page."""
    return render_template("index.html")


@app.route("/api/scrape", methods=["POST"])
def scrape_endpoint():
    """API endpoint called by the frontend fetch request."""
    data = request.get_json() or {}
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "No URL provided."}), 400

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        # max_pages is kept to 15-20 to keep web request response times reasonable
        results = crawl_site(url, max_pages=100)
        sorted_emails = sorted(list(results))
        return jsonify({"count": len(sorted_emails), "emails": sorted_emails})
    except Exception as e:
        return jsonify({"error": f"Scraping error: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)