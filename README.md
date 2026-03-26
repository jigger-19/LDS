# 🎯 Dagelijkse Lead Scraper — Bjorn ZZP

Vindt automatisch elke werkdag 5 Nederlandse MKB-bedrijven die toe zijn aan een nieuwe website of webshop. Stuurt een HTML e-mailrapport met leadanalyse én een call-script per lead.

---

## Wat doet het?

1. **Google Places API** → vindt bedrijven in NL (horeca, retail, bouw, zorg)
2. **PageSpeed API** → checkt hoe slecht hun website presteert
3. **Claude AI** → schrijft per lead een analyse + persoonlijk call-script
4. **Gmail** → stuurt het rapport elke werkdag om 08:30

---

## Opzetten (15 minuten)

### Stap 1 — Repository aanmaken op GitHub

```bash
# Maak een nieuw privé repository aan op github.com
# Upload deze bestanden erin (of push via git)
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/JOUWGEBRUIKER/lead-scraper.git
git push -u origin main
```

### Stap 2 — API Keys regelen

**Google Places + PageSpeed API:**
1. Ga naar https://console.cloud.google.com
2. Maak een nieuw project: "Lead Scraper"
3. Activeer: **Places API** en **PageSpeed Insights API**
4. Ga naar "Credentials" → "Create credentials" → "API key"
5. Kopieer de key (gebruik dezelfde voor Places én PageSpeed)

**Anthropic API key:**
1. Ga naar https://console.anthropic.com
2. "API Keys" → "Create Key"
3. Kopieer de key

**Gmail App Password:**
1. Ga naar https://myaccount.google.com/security
2. Zet 2-staps verificatie aan (verplicht voor app passwords)
3. Zoek "App-wachtwoorden" → maak een nieuw aan voor "Mail"
4. Kopieer het 16-tekens wachtwoord

### Stap 3 — GitHub Secrets instellen

Ga naar jouw GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Voeg deze secrets toe:

| Secret naam            | Waarde                              |
|------------------------|-------------------------------------|
| `GOOGLE_PLACES_API_KEY`| jouw Google API key                 |
| `ANTHROPIC_API_KEY`    | jouw Anthropic API key              |
| `PAGESPEED_API_KEY`    | zelfde als Google API key           |
| `GMAIL_USER`           | jouw Gmail adres (bjorn@gmail.com)  |
| `GMAIL_APP_PASSWORD`   | het 16-tekens app password          |
| `LEADS_TO_EMAIL`       | waar rapport naartoe (mag hetzelfde)|

### Stap 4 — Handmatig testen

Ga naar je repo → **Actions** → **Dagelijkse Lead Scraper** → **Run workflow**

Je ontvangt binnen ~3-5 minuten een e-mail.

### Stap 5 — Automatisch schema

De workflow runt automatisch elke **werkdag om 08:30** (pas aan in `.github/workflows/daily-leads.yml` → de `cron` waarde).

```
'30 6 * * 1-5'   = werkdagen 06:30 UTC = ~08:30 NL zomertijd
'30 7 * * 1-5'   = werkdagen 07:30 UTC = ~08:30 NL wintertijd
```

---

## Kosten (schatting)

| Service           | Kosten per dag      | Kosten per maand   |
|-------------------|---------------------|--------------------|
| Google Places API | ~€0.05 (5 searches) | ~€1.00             |
| PageSpeed API     | Gratis              | €0.00              |
| Anthropic (Claude)| ~€0.05 (5 analyses) | ~€1.00             |
| GitHub Actions    | Gratis (public repo)| €0.00              |
| **Totaal**        | **~€0.10/dag**      | **~€2.00/maand**   |

---

## Branches & locaties

Het script roteert dagelijks automatisch door 13 zoekcombinaties zodat je nooit dezelfde leads ziet. Branches: Horeca, Retail, Bouw, Zorg.

Om branches of steden aan te passen: bewerk `SEARCH_CONFIGS` in `scripts/lead_scraper.py`.

---

## Problemen?

- **Geen leads gevonden** → controleer of je Google API key actief is en Places API enabled heeft
- **E-mail komt niet aan** → controleer App Password (niet je gewone Gmail wachtwoord)
- **Workflow runt niet** → ga naar Actions tab en check of workflows enabled zijn

---

## Toekomst (uitbreidingen)

- [ ] KvK-koppeling voor contactpersoon/beslisser
- [ ] Automatisch opslaan in Google Sheets
- [ ] LinkedIn profiel zoeken van eigenaar
- [ ] Lead scoring (1-5 sterren) op basis van meerdere signalen
- [ ] WhatsApp notificatie via Twilio
