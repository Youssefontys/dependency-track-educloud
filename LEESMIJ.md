# Dependency-Track op de Educloud-VM: voorbeeld

Dependency-Track 5 houdt de SBoM van `main` bij tegen nieuwe lekken, ook als er niets gebouwd wordt. De VM heeft geen
publiek IP, dus GitHub kan hem niets sturen. Daarom haalt een script op de VM zelf elk uur de SBoM van de laatste
geslaagde build van `main` op, en levert hem aan Dependency-Track. Je bekijkt alles via een SSH-tunnel; niets staat
open op internet, dus in de hacking week is dit ook geen doelwit.

**Status: voorbeeld, nog niet gedraaid.** Gecontroleerd is wel: de versies, de digests en de quickstart van het project
(5.1.2), en dat `PUT /api/v1/bom` met projectnaam, versie en `autoCreate` in 5.1.2 bestaat (bron:
`BomResource.java` en `BomSubmitRequest.java` in DependencyTrack/dependency-track).

`terraform/` zet de VM zelf neer op Fontys Educloud (Apache CloudStack) en voert daarna stap 1 t/m 4 hieronder
automatisch uit. De resource-namen en de provider-versie (`~> 0.5.0`) zijn gecontroleerd tegen de officiële
docs van `apache/cloudstack-terraform-provider` op GitHub (2026-10-20); **niet gecontroleerd: of Educloud's eigen
CloudStack-versie dezelfde schema's en user-data-limieten heeft**, en de map is nog niet tegen een echte
Educloud-omgeving gedraaid.

## Wat erin zit

| Bestand | Wat |
|---|---|
| `compose.yaml` | Dependency-Track 5.1.2: API-server, frontend en PostgreSQL 18.6, vast op digest, alleen op 127.0.0.1 |
| `.env.example` | Het databasewachtwoord voor `compose.yaml` |
| `sbom-naar-dtrack.py` | Haalt de SBoM op bij GitHub en levert hem aan Dependency-Track (alleen de standaardbibliotheek) |
| `sbom-naar-dtrack.env.example` | Het token van GitHub en de API-key van Dependency-Track |
| `sbom-naar-dtrack.service`, `.timer` | Draaien het script elk uur, als tijdelijke gebruiker zonder rechten |
| `terraform/` | Zet de VM neer op Educloud en doet stap 1 t/m 4 van "Opzetten" voor je; optioneel, zie onder |
| `terraform/check-verbinding.py` | Los van Terraform: checkt bereik en API-sleutels voor je iets aanmaakt |
| `dt-bootstrap.py` | Doet stap 5 (wachtwoord) en de `DT_API_KEY`-regel van stap 7, via Dependency-Track's eigen REST API |

## Wat de VM nodig heeft

- Minstens 4 GB RAM (de API-server krijgt 2 GB, zoals in de quickstart), Linux met systemd, Docker met Compose v2 en
  Python 3.
- Uitgaand internet: Dependency-Track haalt zelf de gegevens over lekken op, en het script praat met GitHub.
- SSH vanaf je pc, of via de VPN van Fontys.

## Opzetten met Terraform (optioneel, vervangt stap 1 t/m 4 hieronder)

0. Eerst los van Terraform checken of je Educloud überhaupt bereikt en of je sleutels werken, met
   `terraform/check-verbinding.py` (alleen standaardbibliotheek, maakt niets aan):
   ```bash
   export CLOUDSTACK_API_URL=https://<educloud-endpoint>/client/api
   export CLOUDSTACK_API_KEY=...
   export CLOUDSTACK_SECRET_KEY=...
   python3 terraform/check-verbinding.py
   ```
   Lukt dit niet, dan heeft Terraform ook geen zin: eerst de VPN/endpoint/sleutels oplossen.
   Lukt het wel, dan noemt het meteen de exacte zone-namen voor stap 2.
1. In Educloud, onder je account, een API key en secret key genereren (zie ook stap 6 hieronder voor
   het GitHub-token, dat is iets anders).
2. Zoek de exacte namen op van je compute offering, template en zone in de Educloud-UI; hoofdlettergevoelig.
3. ```bash
   cd terraform
   cp terraform.tfvars.example terraform.tfvars
   ```
   Vul `terraform.tfvars` met de API-sleutels en de namen uit stap 2.
4. ```bash
   terraform init
   terraform apply
   ```
   Dit moet draaien vanaf een machine die al op de Fontys-VPN zit: de provisioners verbinden na het
   aanmaken direct over SSH met het privé-IP van de VM, dezelfde eis als de tunnel in stap 4 hieronder.
5. `terraform apply` draait na `bootstrap.sh` ook meteen `dt-bootstrap.py` op de VM: wachtwoord
   zetten, team + permissies + API-key aanmaken via Dependency-Track's REST API, en `DT_API_KEY`
   alvast in `/etc/sbom-naar-dtrack.env` zetten. Het admin-wachtwoord staat na afloop in
   `/root/.dt-admin-password` op de VM (root-only). Ga daarna direct verder bij stap 6 hieronder
   (het GitHub-token, dat kan niet geautomatiseerd).

## Opzetten (met de hand, of verder na Terraform)

1. Kopieer deze map naar de VM, bijvoorbeeld naar `~/dependency-track/`.
2. Maak het wachtwoord voor de database:
   ```bash
   cp .env.example .env && chmod 600 .env
   ```
   Zet in `.env` een lang wachtwoord, bijvoorbeeld uit `openssl rand -hex 32`.
3. Start Dependency-Track. De eerste start duurt even, omdat hij de gegevens over lekken ophaalt.
   ```bash
   docker compose up -d
   ```
4. Open vanaf je pc een tunnel, en daarna `http://localhost:8081` in je browser:
   ```bash
   ssh -L 8081:127.0.0.1:8081 -L 8080:127.0.0.1:8080 <gebruiker>@<vm>
   ```
   Log in als `admin` met wachtwoord `admin`, en kies meteen een nieuw wachtwoord; Dependency-Track vraagt daar zelf om.
5. Maak in Dependency-Track, onder Administration en Access Management, een team met alleen de permissies
   `BOM_UPLOAD` en `PROJECT_CREATION_UPLOAD`, en maak daar een API-key. De namen in de interface kunnen per versie
   iets verschillen. Of: `sudo python3 dt-bootstrap.py` op de VM, doet dit (en het wachtwoord hierboven) via de
   REST API; het admin-wachtwoord komt dan in `/root/.dt-admin-password` te staan.
6. Maak op GitHub een fine-grained token: alleen de repository `secure-application`, alleen "Actions: Read-only", met
   een vervaldatum. Het artifact met de SBoM downloaden vraagt een token, ook bij een openbare repo.
7. Zet het script en de instellingen op hun plek:
   ```bash
   sudo install -D -m 0644 sbom-naar-dtrack.py /opt/sbom-naar-dtrack/sbom-naar-dtrack.py
   sudo install -m 0600 sbom-naar-dtrack.env.example /etc/sbom-naar-dtrack.env
   sudo install -m 0644 sbom-naar-dtrack.service sbom-naar-dtrack.timer /etc/systemd/system/
   ```
   Vul in `/etc/sbom-naar-dtrack.env` het token en de API-key in.
8. Eén keer met de hand, en kijk in de log:
   ```bash
   sudo systemctl daemon-reload && sudo systemctl start sbom-naar-dtrack.service
   journalctl -u sbom-naar-dtrack.service -n 20
   ```
   Daarna staat het project `secure-application`, versie `main`, in Dependency-Track.
9. Elk uur automatisch:
   ```bash
   sudo systemctl enable --now sbom-naar-dtrack.timer
   ```

## Goed om te weten

- **Steeds versie `main`.** Het script levert elke nieuwe SBoM aan dezelfde projectversie. Zo blijven beslissingen die
  je in Dependency-Track over een melding neemt staan, ook na een nieuwe build. Een SBoM die al geleverd is, levert
  het niet nog eens.
- **De VEX uit de repo leest Dependency-Track niet.** `vex/openvex.json` is OpenVEX, en Dependency-Track 5.1.2 leest
  alleen CycloneDX-VEX. De beslissingen uit de VEX zet je dus in Dependency-Track zelf, of je zet de VEX om naar
  CycloneDX.
- **Dezelfde SBoM als de pipeline.** Het script levert de SBoM die Trivy in `image.yml` maakte. Volgens deelvraag 3
  ziet die niet wat een wheel zelf meeneemt; Dependency-Track ziet dus ook niet meer dan die SBoM.
- **Bijwerken gaat met de hand.** De images staan vast op digest. Een nieuwe versie zet je zelf in `compose.yaml`,
  na de upgrade notes van het project; Dependabot kijkt niet op de VM.
- **Een token verloopt.** Na de vervaldatum faalt het script met HTTP 401; maak dan een nieuw token, met dezelfde
  rechten.
