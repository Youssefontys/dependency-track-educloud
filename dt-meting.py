"""Twee metingen voor het onderzoek, tegen de Dependency-Track op deze VM. Alleen de standaardbibliotheek.

  python3 dt-meting.py log         Eén regel in metingen.csv: het moment, de commit van de SBoM, en hoeveel meldingen
                                   Dependency-Track nu heeft per ernst. Draait elk uur na sbom-naar-dtrack.py. Verandert
                                   het aantal terwijl de commit gelijk blijft, dan zag Dependency-Track een nieuw lek
                                   zonder dat er gebouwd is: dat moment naast de eerstvolgende run van de pipeline is de
                                   meting "hoe snel zie je een nieuw lek".
  sudo python3 dt-meting.py vergelijk
                                   Dezelfde SBoM langs drie wegen: Trivy zonder de VEX, Trivy met de VEX (zoals de
                                   pipeline), en Dependency-Track. Laat zien welke lekken Dependency-Track toont die de
                                   VEX in de pipeline wegfiltert, en welke alleen de een of de ander kent. Heeft Docker
                                   nodig voor Trivy, dus met sudo.

Instellingen in de omgeving, of anders uit /etc/sbom-naar-dtrack.env: DT_READ_KEY (een key van een team met alleen
VIEW_PORTFOLIO en VIEW_VULNERABILITY; dt-bootstrap.py maakt hem), en optioneel DT_URL, REPO, PROJECT, STATE en METINGEN.

Status: geschreven en lokaal getest tegen een nagemaakte Dependency-Track; nog niet tegen de echte gedraaid. De
veldnamen van een melding (vulnerability.vulnId, vulnerability.severity, component.purl, analysis.isSuppressed) zijn
die van Dependency-Track 4; het eindpunt GET /v1/finding/project/{uuid} en de permissie VIEW_VULNERABILITY zijn
gecontroleerd in FindingResource.java van 5.1.2."""
import csv
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ENV_FILE = "/etc/sbom-naar-dtrack.env"
AGENT = "dt-meting"
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNASSIGNED")
# Dezelfde Trivy als de pipeline (CI-image.yml), vast op versie en digest: anders meet je twee scanners.
TRIVY = "aquasec/trivy:0.76.0@sha256:2416d1f74045b57274df1a340eee6b510cacd73c66a6ccb8da092b117eb7d222"


def load_env_file():
    # Met de hand gedraaid staan de instellingen niet in de omgeving; systemd geeft ze wel mee.
    try:
        lines = pathlib.Path(ENV_FILE).read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, PermissionError):
        return
    for line in lines:
        name, sep, value = line.partition("=")
        if sep and not name.startswith("#") and name.strip() not in os.environ:
            os.environ[name.strip()] = value.strip()


def setting(name, default=None, pattern=None):
    value = os.environ.get(name, default)
    if not value:
        sys.exit(f"{name} ontbreekt; zie sbom-naar-dtrack.env.example.")
    if pattern and not re.fullmatch(pattern, value):
        sys.exit(f"{name} heeft een onverwachte vorm.")
    return value


def dtrack(path):
    req = urllib.request.Request(DT_URL.rstrip("/") + path, headers={
        "X-Api-Key": READ_KEY, "Accept": "application/json", "User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def findings():
    """Alle meldingen van het project, ook de onderdrukte: [(vulnId, ernst, purl, onderdrukt)]."""
    query = urllib.parse.urlencode({"name": PROJECT, "version": "main"})
    project = dtrack(f"/api/v1/project/lookup?{query}")
    rows, page = [], 1
    while True:
        batch = dtrack(f"/api/v1/finding/project/{project['uuid']}?suppressed=true&pageSize=500&pageNumber={page}")
        for f in batch:
            vuln, comp, analysis = f.get("vulnerability") or {}, f.get("component") or {}, f.get("analysis") or {}
            rows.append((vuln.get("vulnId", "?"), str(vuln.get("severity", "UNASSIGNED")).upper(),
                         comp.get("purl") or comp.get("name", "?"), bool(analysis.get("isSuppressed"))))
        if len(batch) < 500:
            return rows
        page += 1


def delivered_sha():
    return STATE.read_text(encoding="utf-8").strip() if STATE.exists() else ""


def log():
    rows = findings()
    active = [r for r in rows if not r[3]]
    counts = {s: sum(1 for r in active if r[1] == s) for s in SEVERITIES}
    # Een vingerafdruk van welke lekken het zijn: zo zie je ook een wissel bij een gelijk aantal.
    ids = sorted({r[0] for r in active if r[1] in ("CRITICAL", "HIGH")})
    new_file = not METINGEN.exists()
    METINGEN.parent.mkdir(parents=True, exist_ok=True)
    with METINGEN.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["tijd_utc", "commit", *[s.lower() for s in SEVERITIES], "onderdrukt", "high_en_critical"])
        w.writerow([datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"), delivered_sha(),
                    *[counts[s] for s in SEVERITIES], len(rows) - len(active), " ".join(ids)])
    print(f"Gemeten: {counts['CRITICAL']} critical, {counts['HIGH']} high, {len(rows) - len(active)} onderdrukt; "
          f"regel in {METINGEN}.")


def trivy(folder, *extra):
    """De unieke lekken van HIGH en CRITICAL die Trivy in de SBoM vindt: {vulnId: ernst}."""
    cmd = ["docker", "run", "--rm", "-v", f"{folder}:/scan", TRIVY, "sbom", "/scan/sbom.cdx.json", "--format", "json",
           "--severity", "HIGH,CRITICAL", "--quiet", *extra]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"Trivy gaf een fout:\n{out.stderr[-600:]}")
    found = {}
    for result in json.loads(out.stdout).get("Results") or []:
        for v in result.get("Vulnerabilities") or []:
            found[v["VulnerabilityID"]] = v.get("Severity", "?")
    return found


def compare():
    sbom = STATE.with_name("laatste.cdx.json")
    sha = delivered_sha()
    if not (sbom.exists() and sha):
        sys.exit(f"Nog geen SBoM geleverd ({sbom} ontbreekt); draai eerst sbom-naar-dtrack.service.")
    work = pathlib.Path("/tmp/dt-meting")
    work.mkdir(mode=0o700, exist_ok=True)
    (work / "sbom.cdx.json").write_bytes(sbom.read_bytes())
    # De VEX van precies die commit; de repo is openbaar, dus zonder token.
    vex = None
    try:
        with urllib.request.urlopen(urllib.request.Request(
                f"https://raw.githubusercontent.com/{REPO}/{sha}/vex/openvex.json", headers={"User-Agent": AGENT}), timeout=30) as r:
            (work / "openvex.json").write_bytes(r.read())
            vex = True
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    plain = trivy(work)
    filtered = trivy(work, "--vex", "/scan/openvex.json") if vex else None
    rows = findings()
    dt_all = {r[0]: r[1] for r in rows if r[1] in ("CRITICAL", "HIGH")}
    dt_active = {r[0] for r in rows if r[1] in ("CRITICAL", "HIGH") and not r[3]}

    print(f"SBoM van commit {sha[:7]}, project {PROJECT}; alleen HIGH en CRITICAL, unieke lekken.\n")
    print(f"  Trivy zonder VEX            {len(plain):4d}")
    if filtered is None:
        print("  Trivy met VEX                  -   (geen vex/openvex.json bij deze commit)")
    else:
        print(f"  Trivy met VEX (de pipeline) {len(filtered):4d}   de VEX filtert er {len(plain) - len(filtered)} weg")
    print(f"  Dependency-Track, open      {len(dt_active):4d}   en {len(dt_all) - len(dt_active)} onderdrukt in Dependency-Track zelf")
    result = {"commit": sha, "project": PROJECT, "trivy": sorted(plain), "dependency_track_open": sorted(dt_active)}
    if filtered is not None:
        gap = sorted(dt_active & (set(plain) - set(filtered)))
        result["trivy_met_vex"] = sorted(filtered)
        result["open_in_dt_maar_weggefilterd_door_vex"] = gap
        print(f"\n  Open in Dependency-Track, maar door de VEX weggefilterd in de pipeline: {len(gap)}")
        print("  Dependency-Track leest de OpenVEX niet: deze beslissingen staan er niet in.")
    only_dt, only_trivy = sorted(set(dt_all) - set(plain)), sorted(set(plain) - set(dt_all))
    result["alleen_dependency_track"], result["alleen_trivy"] = only_dt, only_trivy
    print(f"\n  Alleen Dependency-Track kent: {len(only_dt)}   alleen Trivy kent: {len(only_trivy)}")
    for name, ids in (("alleen Dependency-Track", only_dt), ("alleen Trivy", only_trivy)):
        if ids:
            print(f"    {name}: {', '.join(ids[:12])}{' ...' if len(ids) > 12 else ''}")
    out = METINGEN.with_name(f"vergelijking-{sha[:7]}.json")
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"\nBewaard in {out}.")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("log", "vergelijk"):
        sys.exit(__doc__)
    load_env_file()
    READ_KEY = setting("DT_READ_KEY", pattern=r"[A-Za-z0-9_\-]{20,200}")
    DT_URL = setting("DT_URL", "http://127.0.0.1:8080", r"https?://[A-Za-z0-9.\-]+(?::\d{1,5})?")
    REPO = setting("REPO", "Youssefontys/secure-app", r"[A-Za-z0-9\-]{1,39}/[A-Za-z0-9._\-]{1,100}")
    PROJECT = setting("PROJECT", "secure-app", r"[A-Za-z0-9._ \-]{1,100}")
    STATE = pathlib.Path(setting("STATE", "/var/lib/sbom-naar-dtrack/laatste"))
    METINGEN = pathlib.Path(setting("METINGEN", str(STATE.with_name("metingen.csv"))))
    try:
        log() if sys.argv[1] == "log" else compare()
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} van {str(e.filename).split('?')[0]}: {e.read(300).decode(errors='replace')}")
    except urllib.error.URLError as e:
        sys.exit(f"Niet bereikbaar: {e.reason}")
