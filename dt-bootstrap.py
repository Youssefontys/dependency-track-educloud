"""Automatiseert stap 5 t/m 8 van README.md tegen Dependency-Track's eigen REST API: het
geforceerde admin-wachtwoord zetten, een team met de juiste permissies maken, en daar een
API-key voor genereren, in /etc/sbom-naar-dtrack.env. Draait op de VM zelf (praat met
127.0.0.1:8080). Alleen de standaardbibliotheek.

Alleen GitHub's fine-grained token (stap 6) blijft handwerk: GitHub heeft bewust geen API om
een nieuw token te laten aanmaken door een ander token, dat zou zelf een manier zijn om rechten
te verhogen. Dat ene stuk kan dus niet, de rest hieronder wel.

Endpoints gecontroleerd tegen de echte 5.1.2-broncode (UserResource.java, TeamResource.java,
PermissionResource.java in DependencyTrack/dependency-track), niet uit het hoofd. Onzeker:
of het antwoord van PUT /v1/team/{uuid}/key echt een los "key"-veld met de volledige,
bruikbare sleutel teruggeeft (zo lijkt het uit Alpine's ApiKey-model, maar nog niet getest
tegen een echte server).

Herhaald draaien is veilig: slaat het wachtwoord zetten en de API-key over als ze al eerder
gelukt zijn (te zien aan /root/.dt-admin-password en een niet-lege DT_API_KEY in het env-bestand).

Gebruik: sudo python3 dt-bootstrap.py
"""
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8080/api/v1"
ENV_FILE = "/etc/sbom-naar-dtrack.env"
PASSWORD_FILE = "/root/.dt-admin-password"
TEAM_NAME = "sbom-naar-dtrack"
PERMISSIONS = ("BOM_UPLOAD", "PROJECT_CREATION_UPLOAD")
# Voor dt-meting.py: alleen lezen. Gecontroleerd in 5.1.2: het opvragen van meldingen vraagt VIEW_VULNERABILITY
# (FindingResource.java); het opzoeken van het project op naam VIEW_PORTFOLIO.
READ_TEAM_NAME = "dt-meting"
READ_PERMISSIONS = ("VIEW_PORTFOLIO", "VIEW_VULNERABILITY")


def request(method, path, body=None, token=None, form=None):
    # Niet alleen application/json eisen: forceChangePassword en login geven text/plain terug,
    # en kregen daardoor een 406 van de server toen dit nog hard op json stond.
    headers = {"Accept": "*/*"}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers=headers)
    # urlopen gooit bij elke status van 300 of hoger een HTTPError; dan kwam de code hieronder nooit bij een 409
    # ("team bestaat al") of 304 ("permissie stond er al"). Daarom de status teruggeven in plaats van stoppen.
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def wait_for_dt():
    # /version hangt hier onder /api, niet onder /api/v1 (het is een los Alpine-resource,
    # geen Dependency-Track-eigen v1-endpoint); vandaar de losse, volledige URL.
    print("Wachten tot Dependency-Track de API beantwoordt (duurt even bij de eerste start)...")
    for _ in range(60):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/api/version", timeout=10):
                pass
            print("Dependency-Track antwoordt.")
            return
        except Exception:
            time.sleep(10)
    sys.exit("Dependency-Track antwoordt na 10 minuten nog niet; kijk in 'docker compose logs apiserver'.")


def get_admin_token():
    """Geeft (token). Drie paden: een bewaard wachtwoord van een vorige run, een al bij de
    hand bekend wachtwoord via DT_ADMIN_PASSWORD (bijv. omdat het via de UI is gezet, zoals
    hier), of anders de standaard admin/admin die wordt omgezet naar iets nieuws."""
    try:
        with open(PASSWORD_FILE, encoding="utf-8") as f:
            password = f.read().strip()
        print("Bestaand wachtwoord gevonden, forceChangePassword overgeslagen.")
    except FileNotFoundError:
        known_password = os.environ.get("DT_ADMIN_PASSWORD")
        if known_password:
            status, _ = request("POST", "/user/login", form={"username": "admin", "password": known_password})
            if status != 200:
                sys.exit(f"Inloggen met DT_ADMIN_PASSWORD gaf status {status}; klopt het wachtwoord nog?")
            password = known_password
            print("Al bekend wachtwoord werkt.")
        else:
            password = secrets.token_urlsafe(32)
            status, _ = request(
                "POST", "/user/forceChangePassword",
                form={"username": "admin", "password": "admin", "newPassword": password, "confirmPassword": password},
            )
            if status != 200:
                sys.exit(
                    f"forceChangePassword gaf status {status}. Staat het wachtwoord al op iets "
                    "anders dan admin/admin? Zet dan DT_ADMIN_PASSWORD en draai opnieuw."
                )
            print("Wachtwoord gezet.")
        with open(PASSWORD_FILE, "w", encoding="utf-8") as f:
            f.write(password + "\n")
        os.chmod(PASSWORD_FILE, 0o600)
        print(f"Bewaard in {PASSWORD_FILE} (root-only).")

    status, body = request("POST", "/user/login", form={"username": "admin", "password": password})
    if status != 200:
        sys.exit(f"Inloggen als admin gaf status {status}.")
    return body.decode().strip()


def get_or_create_team(token, name):
    status, body = request("PUT", "/team", body={"name": name}, token=token)
    if status == 201:
        print(f"Team '{name}' aangemaakt.")
        return json.loads(body)["uuid"]
    if status == 409:
        print(f"Team '{name}' bestaat al, hergebruiken.")
        _, body = request("GET", "/team", token=token)
        for team in json.loads(body):
            if team["name"] == name:
                return team["uuid"]
        sys.exit(f"Team '{name}' meldt zich als bestaand (409) maar staat niet in de lijst.")
    sys.exit(f"Team aanmaken gaf onverwachte status {status}.")


def grant_permissions(token, team_uuid, permissions):
    for permission in permissions:
        status, _ = request("POST", f"/permission/{permission}/team/{team_uuid}", body={}, token=token)
        if status not in (200, 304):
            sys.exit(f"Permissie {permission} toekennen gaf status {status}.")
        print(f"Permissie {permission}: in orde (status {status}).")


def ensure_api_key(token, team_uuid, variable):
    try:
        with open(ENV_FILE, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []
    for line in lines:
        if line.startswith(f"{variable}=") and line.strip() != f"{variable}=":
            print(f"{ENV_FILE} heeft al een {variable}, niets nieuws gegenereerd.")
            return

    status, body = request("PUT", f"/team/{team_uuid}/key", token=token)
    if status != 201:
        sys.exit(f"API-key genereren gaf status {status}.")
    key = json.loads(body)["key"]

    new_lines = [l for l in lines if not l.startswith(f"{variable}=")]
    new_lines.append(f"{variable}={key}\n")
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    os.chmod(ENV_FILE, 0o600)
    print(f"API-key gegenereerd en als {variable} in {ENV_FILE} gezet.")


def main():
    wait_for_dt()
    token = get_admin_token()
    # Twee teams, elk met alleen wat het nodig heeft: leveren mag niet lezen, meten mag niet leveren.
    for name, permissions, variable in ((TEAM_NAME, PERMISSIONS, "DT_API_KEY"), (READ_TEAM_NAME, READ_PERMISSIONS, "DT_READ_KEY")):
        team_uuid = get_or_create_team(token, name)
        grant_permissions(token, team_uuid, permissions)
        ensure_api_key(token, team_uuid, variable)
    print("\nKlaar. Resterend handwerk: alleen nog het GitHub-token zelf aanmaken en in "
          f"{ENV_FILE} zetten (GITHUB_TOKEN=...), en dan:")
    print("  sudo systemctl daemon-reload && sudo systemctl start sbom-naar-dtrack.service")
    print("  sudo systemctl enable --now sbom-naar-dtrack.timer")


try:
    main()
except urllib.error.HTTPError as e:
    sys.exit(f"HTTP {e.code} van Dependency-Track: {e.read(300).decode(errors='replace')}")
except urllib.error.URLError as e:
    sys.exit(f"Niet bereikbaar: {e.reason}. Draait dit wel op de VM zelf, niet op je eigen pc?")
