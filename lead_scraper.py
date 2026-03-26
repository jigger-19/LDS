"""
Dagelijkse Lead Scraper voor Bjorn Scheepens — ZZP Shopify/WordPress projecten
Vindt 5 Nederlandse bedrijven met verouderde websites en stuurt een e-mail rapport.

Vereiste env-variabelen:
  GOOGLE_PLACES_API_KEY  — Google Places API key
  ANTHROPIC_API_KEY      — Anthropic API key
  PAGESPEED_API_KEY      — Google PageSpeed API key (zelfde als Places of apart)
  GMAIL_USER             — Jouw Gmail adres (bjorn@...)
  GMAIL_APP_PASSWORD     — Gmail App Password (niet je gewone wachtwoord)
  LEADS_TO_EMAIL         — E-mailadres waar rapport naartoe gaat (mag hetzelfde zijn)
"""

import os
import json
import random
import smtplib
import datetime
import time
import urllib.request
import urllib.parse
import urllib.error
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import anthropic

# ─────────────────────────────────────────────
# CONFIGURATIE
# ─────────────────────────────────────────────

PLACES_API_KEY   = os.environ["GOOGLE_PLACES_API_KEY"]
ANTHROPIC_KEY    = os.environ["ANTHROPIC_API_KEY"]
PAGESPEED_KEY    = os.environ.get("PAGESPEED_API_KEY", PLACES_API_KEY)
GMAIL_USER       = os.environ["GMAIL_USER"]
GMAIL_PASS       = os.environ["GMAIL_APP_PASSWORD"]
LEADS_TO_EMAIL   = os.environ["LEADS_TO_EMAIL"]

LEADS_PER_DAY    = 5
MIN_WEBSITE_AGE  = 4   # jaren — alleen sites ouder dan dit
SLEEP_BETWEEN    = 1.5 # seconden tussen API calls

# Branches & zoekopdrachten (roteert dagelijks zodat je steeds verse leads krijgt)
SEARCH_CONFIGS = [
    # (branche_label, google_query, stad_pool)
    ("Horeca",   "restaurant",          ["Amsterdam", "Rotterdam", "Utrecht", "Den Haag", "Eindhoven", "Groningen", "Tilburg", "Breda", "Nijmegen", "Haarlem"]),
    ("Horeca",   "cafe bar kroeg",      ["Zwolle", "Leeuwarden", "Amersfoort", "Deventer", "Maastricht", "Alkmaar", "Dordrecht", "Leiden", "Enschede", "Arnhem"]),
    ("Retail",   "kledingwinkel",       ["Amsterdam", "Rotterdam", "Utrecht", "Den Haag", "Eindhoven"]),
    ("Retail",   "meubelwinkel",        ["Tilburg", "Breda", "Nijmegen", "Haarlem", "Zwolle"]),
    ("Retail",   "sieradenwinkel",      ["Amsterdam", "Den Haag", "Rotterdam", "Utrecht", "Groningen"]),
    ("Bouw",     "loodgieter",          ["Amsterdam", "Rotterdam", "Utrecht", "Den Haag", "Eindhoven", "Tilburg"]),
    ("Bouw",     "dakdekker",           ["Groningen", "Haarlem", "Leiden", "Zwolle", "Amersfoort"]),
    ("Bouw",     "installatiebedrijf",  ["Amsterdam", "Rotterdam", "Utrecht", "Eindhoven", "Breda"]),
    ("Bouw",     "schildersbedrijf",    ["Nijmegen", "Arnhem", "Dordrecht", "Alkmaar", "Enschede"]),
    ("Zorg",     "kapsalon",            ["Amsterdam", "Rotterdam", "Utrecht", "Den Haag", "Eindhoven", "Tilburg", "Groningen"]),
    ("Zorg",     "schoonheidssalon",    ["Haarlem", "Breda", "Nijmegen", "Zwolle", "Leiden"]),
    ("Zorg",     "fysiotherapeut",      ["Amsterdam", "Rotterdam", "Utrecht", "Den Haag", "Eindhoven"]),
    ("Zorg",     "tandarts",            ["Groningen", "Tilburg", "Haarlem", "Amersfoort", "Dordrecht"]),
]

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def fetch_json(url: str) -> dict:
    """Eenvoudige GET die JSON teruggeeft, zonder externe dependencies."""
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


def find_businesses(query: str, city: str, max_results: int = 20) -> list[dict]:
    """Haalt bedrijven op via Google Places Text Search."""
    full_query = f"{query} {city} Nederland"
    encoded    = urllib.parse.quote(full_query)
    url = (
        f"https://maps.googleapis.com/maps/api/place/textsearch/json"
        f"?query={encoded}&region=nl&language=nl&key={PLACES_API_KEY}"
    )
    data    = fetch_json(url)
    results = data.get("results", [])
    time.sleep(SLEEP_BETWEEN)
    return results[:max_results]


def get_place_details(place_id: str) -> dict:
    """Haalt extra details op: website, telefoonnummer, adres."""
    fields = "name,formatted_address,formatted_phone_number,website,rating,user_ratings_total,opening_hours"
    url = (
        f"https://maps.googleapis.com/maps/api/place/details/json"
        f"?place_id={place_id}&fields={fields}&language=nl&key={PLACES_API_KEY}"
    )
    data = fetch_json(url)
    time.sleep(SLEEP_BETWEEN)
    return data.get("result", {})


def check_pagespeed(url: str) -> dict:
    """Checkt laadsnelheid & basisinfo via PageSpeed API."""
    encoded = urllib.parse.quote(url, safe="")
    api_url = (
        f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
        f"?url={encoded}&strategy=mobile&key={PAGESPEED_KEY}"
        f"&category=performance"
    )
    data = fetch_json(api_url)
    if "error" in data:
        return {"available": False, "error": data["error"]}

    lcp = perf = fcp = None
    try:
        cats  = data.get("lighthouseResult", {}).get("categories", {})
        perf  = round((cats.get("performance", {}).get("score", 0) or 0) * 100)
        audits = data.get("lighthouseResult", {}).get("audits", {})
        lcp   = audits.get("largest-contentful-paint", {}).get("displayValue", "?")
        fcp   = audits.get("first-contentful-paint", {}).get("displayValue", "?")
    except Exception:
        pass

    return {
        "available":    True,
        "perf_score":   perf,
        "lcp":          lcp,
        "fcp":          fcp,
    }


def is_weak_website(details: dict, ps: dict) -> bool:
    """Bepaalt of een bedrijf een slechte/verouderde website heeft."""
    if not details.get("website"):
        return True   # geen website = directe kandidaat
    if ps.get("available") and ps.get("perf_score") is not None:
        if ps["perf_score"] < 50:
            return True
    return False


def pick_daily_searches() -> list[tuple]:
    """
    Kiest dagelijks een andere set zoekopdrachten zodat je niet steeds
    dezelfde steden/branches ziet. Gebruikt de dag van het jaar als seed.
    """
    day_seed = datetime.date.today().timetuple().tm_yday
    rng      = random.Random(day_seed)
    pool     = SEARCH_CONFIGS.copy()
    rng.shuffle(pool)
    # Kies zodat alle branches vertegenwoordigd zijn
    selected = []
    seen_branches = set()
    for config in pool:
        branch = config[0]
        if branch not in seen_branches or len(selected) < 3:
            selected.append(config)
            seen_branches.add(branch)
        if len(selected) >= 6:
            break
    return selected


# ─────────────────────────────────────────────
# LEADS VERZAMELEN
# ─────────────────────────────────────────────

def collect_leads(target: int = LEADS_PER_DAY) -> list[dict]:
    """Verzamelt leads totdat we er `target` sterke hebben."""
    searches = pick_daily_searches()
    leads    = []
    seen_ids = set()

    print(f"[{datetime.datetime.now():%H:%M}] Start lead-search voor {datetime.date.today()}")

    for (branch, query, cities) in searches:
        if len(leads) >= target:
            break

        day_seed = datetime.date.today().timetuple().tm_yday
        city = random.Random(day_seed + hash(query)).choice(cities)

        print(f"  Zoek: '{query}' in {city} ({branch})")
        businesses = find_businesses(query, city, max_results=15)

        for biz in businesses:
            if len(leads) >= target:
                break

            place_id = biz.get("place_id", "")
            if not place_id or place_id in seen_ids:
                continue
            seen_ids.add(place_id)

            details = get_place_details(place_id)
            website = details.get("website", "")

            ps = {}
            if website:
                ps = check_pagespeed(website)

            if not is_weak_website(details, ps):
                continue  # website ziet er OK uit, overslaan

            lead = {
                "naam":      details.get("name", biz.get("name", "Onbekend")),
                "branche":   branch,
                "query":     query,
                "stad":      city,
                "adres":     details.get("formatted_address", ""),
                "telefoon":  details.get("formatted_phone_number", ""),
                "website":   website or "(geen website)",
                "rating":    details.get("rating", ""),
                "reviews":   details.get("user_ratings_total", 0),
                "perf":      ps,
                "place_id":  place_id,
            }
            leads.append(lead)
            print(f"    ✅ Lead gevonden: {lead['naam']} ({lead['stad']})")

    print(f"  Totaal {len(leads)} leads verzameld.")
    return leads[:target]


# ─────────────────────────────────────────────
# CLAUDE ANALYSE
# ─────────────────────────────────────────────

def analyse_leads_with_claude(leads: list[dict]) -> list[dict]:
    """Laat Claude per lead een beschrijving en call-script schrijven."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    enriched = []
    for i, lead in enumerate(leads, 1):
        print(f"  Claude analyseert lead {i}/{len(leads)}: {lead['naam']}")

        perf_info = ""
        if lead["perf"].get("available"):
            perf_info = (
                f"PageSpeed score (mobiel): {lead['perf'].get('perf_score', '?')}/100 | "
                f"LCP: {lead['perf'].get('lcp', '?')} | FCP: {lead['perf'].get('fcp', '?')}"
            )
        elif lead["website"] == "(geen website)":
            perf_info = "Geen website gevonden"
        else:
            perf_info = "Website niet bereikbaar of score onbekend"

        prompt = f"""Je bent Bjorn Scheepens, een Nederlandse freelance Shopify-developer die zelfstandig webshops en websites bouwt voor het MKB.

Je hebt de volgende lead gevonden die waarschijnlijk toe is aan een nieuwe website of webshop:

Naam: {lead['naam']}
Branche: {lead['branche']} ({lead['query']})
Stad: {lead['stad']}
Adres: {lead['adres']}
Telefoon: {lead['telefoon']}
Website: {lead['website']}
Google rating: {lead['rating']} ⭐ ({lead['reviews']} reviews)
{perf_info}

Schrijf:

1. **LEAD ANALYSE** (5-8 zinnen):
   - Waarom heeft dit bedrijf waarschijnlijk een nieuwe website/webshop nodig?
   - Wat zijn concrete tekortkomingen? (verouderd design, geen mobiele versie, trage laadtijd, geen webshop, geen SSL, etc.)
   - Welke kansen zie jij als Shopify-developer? (online bestellingen, boekingen, productcatalogus, etc.)
   - Hoe sterk schat je deze lead in (⭐ zwak / ⭐⭐ matig / ⭐⭐⭐ sterk)?

2. **CALL SCRIPT** (voor een cold call van ~2-3 minuten):
   - Professionele Nederlandse openingszin
   - Concrete haak gebaseerd op hun situatie (noem iets specifieks)
   - Waardepropositie in 1-2 zinnen
   - Soft close / afspraak vragen
   - Bezwaar-antwoord voor "we zijn tevreden met onze website"
   - Afsluiting als ze niet geïnteresseerd zijn

Schrijf de call-script in de eerste persoon ("Ik ben Bjorn..."). Gebruik een vriendelijke maar zelfverzekerde toon. Vermijd verkoopjargon.

Antwoord ALLEEN met de twee gevraagde secties, in het Nederlands, zonder inleiding of nawoord."""

        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )

        lead["claude_analyse"] = msg.content[0].text
        enriched.append(lead)
        time.sleep(0.5)

    return enriched


# ─────────────────────────────────────────────
# E-MAIL RAPPORT
# ─────────────────────────────────────────────

def build_html_report(leads: list[dict]) -> str:
    today_str = datetime.date.today().strftime("%d %B %Y")

    cards = ""
    for i, lead in enumerate(leads, 1):
        has_website = lead["website"] != "(geen website)"
        website_badge = (
            f'<a href="{lead["website"]}" style="color:#0070f3">{lead["website"]}</a>'
            if has_website else
            '<span style="color:#e53e3e;font-weight:600">⚠️ Geen website</span>'
        )

        perf_html = ""
        if lead["perf"].get("available"):
            score = lead["perf"].get("perf_score", "?")
            color = "#e53e3e" if (score or 100) < 50 else "#d69e2e" if (score or 100) < 75 else "#38a169"
            perf_html = f'<span style="color:{color};font-weight:700">{score}/100 📱</span> &nbsp; LCP: {lead["perf"].get("lcp","?")} &nbsp; FCP: {lead["perf"].get("fcp","?")}'
        elif not has_website:
            perf_html = '<span style="color:#e53e3e">Geen website</span>'
        else:
            perf_html = '<span style="color:#718096">Score niet beschikbaar</span>'

        # Split Claude analyse in twee delen op het kopje
        analyse_raw = lead.get("claude_analyse", "")
        parts = analyse_raw.split("**CALL SCRIPT**")
        analyse_deel  = parts[0].replace("**LEAD ANALYSE**", "").strip() if len(parts) > 1 else analyse_raw
        callscript_deel = parts[1].strip() if len(parts) > 1 else ""

        # Formateer als HTML (newlines → <br>)
        def nl2br(txt):
            return txt.replace("\n", "<br>")

        rating_stars = f"{'⭐' * int(lead['rating'])}" if lead.get("rating") else "–"

        cards += f"""
        <div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:28px;margin-bottom:28px;box-shadow:0 1px 4px rgba(0,0,0,.06)">
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
            <div style="background:#0070f3;color:#fff;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:16px;flex-shrink:0">{i}</div>
            <div>
              <h2 style="margin:0;font-size:20px;color:#1a202c">{lead['naam']}</h2>
              <span style="background:#ebf8ff;color:#2b6cb0;font-size:12px;font-weight:600;padding:2px 8px;border-radius:20px">{lead['branche']}</span>
              &nbsp;<span style="color:#718096;font-size:13px">📍 {lead['stad']}</span>
            </div>
          </div>

          <table style="width:100%;border-collapse:collapse;font-size:14px;margin-bottom:20px">
            <tr style="border-bottom:1px solid #f7fafc">
              <td style="padding:7px 0;color:#718096;width:130px">📞 Telefoon</td>
              <td style="padding:7px 0;font-weight:600;color:#1a202c">{lead['telefoon'] or '—'}</td>
            </tr>
            <tr style="border-bottom:1px solid #f7fafc">
              <td style="padding:7px 0;color:#718096">🌐 Website</td>
              <td style="padding:7px 0">{website_badge}</td>
            </tr>
            <tr style="border-bottom:1px solid #f7fafc">
              <td style="padding:7px 0;color:#718096">⚡ PageSpeed</td>
              <td style="padding:7px 0">{perf_html}</td>
            </tr>
            <tr>
              <td style="padding:7px 0;color:#718096">⭐ Google</td>
              <td style="padding:7px 0">{rating_stars} <span style="color:#718096;font-size:12px">({lead['reviews']} reviews)</span></td>
            </tr>
          </table>

          <div style="background:#f0fff4;border-left:4px solid #38a169;border-radius:0 8px 8px 0;padding:16px;margin-bottom:16px">
            <p style="margin:0 0 8px 0;font-weight:700;color:#276749;font-size:14px">📊 LEAD ANALYSE</p>
            <p style="margin:0;color:#2d3748;font-size:14px;line-height:1.7">{nl2br(analyse_deel)}</p>
          </div>

          <div style="background:#fffaf0;border-left:4px solid #d69e2e;border-radius:0 8px 8px 0;padding:16px">
            <p style="margin:0 0 8px 0;font-weight:700;color:#744210;font-size:14px">📞 CALL SCRIPT</p>
            <p style="margin:0;color:#2d3748;font-size:14px;line-height:1.8;white-space:pre-wrap">{nl2br(callscript_deel)}</p>
          </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="nl">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f7fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <div style="max-width:700px;margin:0 auto;padding:24px 16px">

    <div style="background:linear-gradient(135deg,#0070f3,#0050c8);color:#fff;border-radius:12px;padding:28px;margin-bottom:28px;text-align:center">
      <p style="margin:0 0 4px 0;font-size:13px;opacity:.8;text-transform:uppercase;letter-spacing:1px">Dagelijks Lead Rapport</p>
      <h1 style="margin:0 0 8px 0;font-size:28px;font-weight:800">{len(leads)} Leads voor {today_str}</h1>
      <p style="margin:0;opacity:.85;font-size:14px">Shopify & WordPress — Nederlandse MKB-bedrijven toe aan een nieuwe website</p>
    </div>

    {cards}

    <div style="text-align:center;color:#a0aec0;font-size:12px;margin-top:16px;padding-bottom:24px">
      Automatisch gegenereerd door je dagelijkse lead scraper 🤖<br>
      Data: Google Places API + PageSpeed API + Claude AI
    </div>
  </div>
</body>
</html>"""

    return html


def send_email(leads: list[dict]) -> None:
    today_str  = datetime.date.today().strftime("%d %B %Y")
    subject    = f"🎯 {len(leads)} nieuwe leads — {today_str}"
    html_body  = build_html_report(leads)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = LEADS_TO_EMAIL
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASS)
        server.sendmail(GMAIL_USER, LEADS_TO_EMAIL, msg.as_string())

    print(f"  ✉️  E-mail verstuurd naar {LEADS_TO_EMAIL}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("=" * 55)
    print(f"  LEAD SCRAPER — {datetime.date.today()}")
    print("=" * 55)

    print("\n📍 Stap 1: Leads verzamelen via Google Places...")
    leads = collect_leads(LEADS_PER_DAY)

    if not leads:
        print("❌ Geen leads gevonden. Controleer je API key en quota.")
        return

    print(f"\n🤖 Stap 2: Claude analyseert {len(leads)} leads...")
    leads = analyse_leads_with_claude(leads)

    print("\n📧 Stap 3: E-mailrapport versturen...")
    send_email(leads)

    print("\n✅ Klaar!")


if __name__ == "__main__":
    main()
