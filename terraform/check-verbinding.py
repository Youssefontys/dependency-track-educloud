"""Checkt, voor je Terraform aanraakt, of je Educloud (CloudStack) kunt bereiken en of je
API-key/secret-key werken. Doet een ondertekende listZones-aanroep; maakt niets aan, wijzigt
niets. Alleen de standaardbibliotheek; werkt op Linux en Windows.

Instellingen in de omgeving, nooit als argument (zou in je shell-geschiedenis belanden):
  CLOUDSTACK_API_URL    bijv. https://<educloud-endpoint>/client/api
  CLOUDSTACK_API_KEY
  CLOUDSTACK_SECRET_KEY

Handtekening-algoritme letterlijk uit de officiële Developer's Guide van Apache CloudStack
(docs.cloudstack.apache.org/en/4.22.1.0/developersguide/dev.html), overgezet naar Python 3:
velden alfabetisch sorteren, de verstuurde querystring normaal urlencoden, en daarnaast een
apart ondertekenings-string opbouwen met lowercase velden/waarden en spaties als %20 in plaats
van +, daar HMAC-SHA1 overheen met de secret key, base64, en urlencoden als &signature=...

Gebruik: python3 check-verbinding.py
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

AGENT = "check-verbinding"


def setting(name):
    value = os.environ.get(name)
    if not value:
        sys.exit(f"{name} ontbreekt; zet hem in de omgeving voor je dit script draait.")
    return value


API_URL = setting("CLOUDSTACK_API_URL")
API_KEY = setting("CLOUDSTACK_API_KEY")
SECRET_KEY = setting("CLOUDSTACK_SECRET_KEY")


def call(command, **params):
    params = {**params, "command": command, "apikey": API_KEY, "response": "json"}
    items = sorted(params.items())
    # Wat echt verstuurd wordt: normale urlencoding, originele hoofdletters.
    request_str = "&".join(f"{k}={urllib.parse.quote_plus(v)}" for k, v in items)
    # Alleen voor de handtekening: key lowercase, value urlencoded+lowercase, "+" naar "%20".
    sig_str = "&".join(
        f"{k.lower()}={urllib.parse.quote_plus(v).lower().replace('+', '%20')}" for k, v in items
    )
    digest = hmac.new(SECRET_KEY.encode(), sig_str.encode(), hashlib.sha1).digest()
    signature = urllib.parse.quote_plus(base64.b64encode(digest).decode().strip())
    url = f"{API_URL.rstrip('/')}?{request_str}&signature={signature}"
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def main():
    result = call("listZones")
    zones = result.get("listzonesresponse", {}).get("zone", [])
    if not zones:
        print("Verbinding en authenticatie werken, maar dit account ziet geen zones.")
        return
    print(f"Verbinding en authenticatie werken. {len(zones)} zone(s) zichtbaar voor dit account:")
    for z in zones:
        print(f"  - {z.get('name')}  (id: {z.get('id')})")

    offerings = call("listServiceOfferings").get("listserviceofferingsresponse", {}).get("serviceoffering", [])
    print(f"\n{len(offerings)} compute offering(s):")
    for o in offerings:
        print(f"  - {o.get('name')}  (cpu: {o.get('cpunumber')}, ram: {o.get('memory')} MB)")

    templates = call("listTemplates", templatefilter="executable").get("listtemplatesresponse", {}).get("template", [])
    print(f"\n{len(templates)} bruikbare template(s):")
    for t in templates:
        print(f"  - {t.get('name')}  (os: {t.get('ostypename')})")

    networks = call("listNetworks").get("listnetworksresponse", {}).get("network", [])
    print(f"\n{len(networks)} netwerk(en):")
    for n in networks:
        print(f"  - {n.get('name')}  (id: {n.get('id')}, state: {n.get('state')})")

    projects = call("listProjects").get("listprojectsresponse", {}).get("project", [])
    print(f"\n{len(projects)} project(en) (gedeelde team-omgevingen):")
    for p in projects:
        print(f"  - {p.get('name')}  (id: {p.get('id')}, account: {p.get('account')})")


try:
    main()
except urllib.error.HTTPError as e:
    body = e.read(500).decode(errors="replace")
    if e.code == 401:
        sys.exit(f"HTTP 401: de server is bereikbaar, maar API_KEY/SECRET_KEY kloppen niet of "
                  f"de handtekening klopt niet.\n{body}")
    sys.exit(f"HTTP {e.code} van de server:\n{body}")
except urllib.error.URLError as e:
    sys.exit(f"Niet bereikbaar: {e.reason}. Zit je op de Fontys-VPN, en klopt CLOUDSTACK_API_URL "
              f"(moet eindigen op /client/api)?")
