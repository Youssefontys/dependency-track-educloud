"""Haalt de SBoM van de laatste geslaagde build van main op bij GitHub, en levert hem aan Dependency-Track.
Voor een VM zonder publiek IP: het script haalt zelf op, dus GitHub hoeft de VM niet te bereiken. Alleen de
standaardbibliotheek; werkt op Linux en Windows. Draait elk uur via sbom-naar-dtrack.timer.
Instellingen in de omgeving (zie sbom-naar-dtrack.env.example): GITHUB_TOKEN en DT_API_KEY, en optioneel DT_URL,
REPO, WORKFLOW, PROJECT en STATE.
Gebruik: python3 sbom-naar-dtrack.py"""
import base64
import io
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile

GITHUB = "https://api.github.com"
AGENT = "sbom-naar-dtrack"


def setting(name, default=None, pattern=None):
    # Alleen waarden in de verwachte vorm; een fout zegt welke instelling, nooit de waarde zelf.
    value = os.environ.get(name, default)
    if not value:
        sys.exit(f"{name} ontbreekt; zie sbom-naar-dtrack.env.example.")
    if pattern and not re.fullmatch(pattern, value):
        sys.exit(f"{name} heeft een onverwachte vorm.")
    return value


TOKEN = setting("GITHUB_TOKEN", pattern=r"(?:github_pat_|ghp_)[A-Za-z0-9_]{20,255}")
API_KEY = setting("DT_API_KEY", pattern=r"[A-Za-z0-9_\-]{20,200}")
DT_URL = setting("DT_URL", "http://127.0.0.1:8080", r"https?://[A-Za-z0-9.\-]+(?::\d{1,5})?")
REPO = setting("REPO", "Youssefontys/secure-app", r"[A-Za-z0-9\-]{1,39}/[A-Za-z0-9._\-]{1,100}")
# De bestandsnaam van de workflow die de SBoM maakt; een andere naam geeft HTTP 404.
WORKFLOW = setting("WORKFLOW", "CI-image.yml", r"[A-Za-z0-9._\-]{1,100}\.ya?ml")
PROJECT = setting("PROJECT", "secure-app", r"[A-Za-z0-9._ \-]{1,100}")
STATE = pathlib.Path(setting("STATE", str(pathlib.Path.home() / ".sbom-naar-dtrack")))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # GitHub stuurt een download door naar opslag met een eigen, ondertekende link; daar hoort het token niet mee.
    def redirect_request(self, *args, **kwargs):
        return None


def github(path):
    req = urllib.request.Request(GITHUB + path, headers={
        "Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def download(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": AGENT})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307, 308) or not e.headers.get("Location"):
            raise
        with urllib.request.urlopen(urllib.request.Request(e.headers["Location"], headers={"User-Agent": AGENT}),
                                    timeout=120) as r:
            return r.read()


def dtrack(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(DT_URL.rstrip("/") + path, data=data, method=method, headers={
        "X-Api-Key": API_KEY, "Content-Type": "application/json", "Accept": "application/json", "User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def main():
    # De laatste geslaagde build van main na een push: daar hoort de SBoM bij die de pipeline scande.
    runs = github(f"/repos/{REPO}/actions/workflows/{WORKFLOW}/runs?branch=main&event=push&status=success&per_page=1")
    if not runs.get("workflow_runs"):
        sys.exit("Geen geslaagde build van main gevonden.")
    run = runs["workflow_runs"][0]
    sha = run["head_sha"]
    if STATE.exists() and STATE.read_text(encoding="utf-8").strip() == sha:
        print(f"Al geleverd: {sha[:7]}; niets te doen.")
        return
    artifacts = github(f"/repos/{REPO}/actions/runs/{run['id']}/artifacts")["artifacts"]
    art = next((a for a in artifacts if a["name"] == f"sbom-{sha}" and not a["expired"]), None)
    if art is None:
        sys.exit(f"Geen SBoM bij run {run['id']} (verlopen na 90 dagen, of de build maakte er geen).")
    with zipfile.ZipFile(io.BytesIO(download(art["archive_download_url"]))) as z:
        sbom = z.read("sbom.cdx.json")
    json.loads(sbom)
    # Steeds dezelfde projectversie, main: zo blijven beslissingen over een melding in Dependency-Track staan.
    token = dtrack("PUT", "/api/v1/bom", {"projectName": PROJECT, "projectVersion": "main", "autoCreate": True,
                                          "isLatest": True, "bom": base64.b64encode(sbom).decode("ascii")})["token"]
    for _ in range(24):
        if not dtrack("GET", f"/api/v1/bom/token/{token}").get("processing"):
            break
        time.sleep(5)
    else:
        print("Dependency-Track verwerkt de SBoM nog; kijk later in de interface.")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    # De SBoM zelf ernaast: dt-meting.py vergelijk scant precies deze met Trivy.
    STATE.with_name("laatste.cdx.json").write_bytes(sbom)
    STATE.write_text(sha + "\n", encoding="utf-8")
    print(f"Geleverd: de SBoM van {sha[:7]} (run {run['id']}) aan {PROJECT}, versie main.")


try:
    main()
except urllib.error.HTTPError as e:
    # Alleen de status en het begin van het antwoord; nooit de headers, daar staat het token in.
    sys.exit(f"HTTP {e.code} van {str(e.filename).split('?')[0]}: {e.read(300).decode(errors='replace')}")
except urllib.error.URLError as e:
    sys.exit(f"Niet bereikbaar: {e.reason}")
