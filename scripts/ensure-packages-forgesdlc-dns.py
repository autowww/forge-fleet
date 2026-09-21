#!/usr/bin/env python3
"""Ensure packages.forgesdlc.com CNAME + Firebase Hosting custom domain."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HOSTNAME = "packages.forgesdlc.com"
CNAME_TARGET = "forge-packages.web.app"
# GCP projects (do not use lenses-d0fdb or other app defaults for this stack):
#   forge-sdlc    — Cloud DNS zone forgesdlc-com (forgesdlc.com)
#   fleet-2f1d3   — Firebase Hosting site forge-packages
FIREBASE_PROJECT = "fleet-2f1d3"
FIREBASE_SITE = "forge-packages"
DNS_PROJECT = "forge-sdlc"
DNS_ZONE = "forgesdlc-com"
DNS_PROJECTS = (DNS_PROJECT, "fleet-2f1d3", "forge-sdlc-blueprints")
CONFIG = Path.home() / ".config/configstore/firebase-tools.json"


def die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def load_firebase_tokens() -> dict:
    if not CONFIG.is_file():
        die(f"missing {CONFIG}; run: firebase login --reauth")
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    tokens = data.get("tokens") or {}
    if not tokens.get("refresh_token"):
        die("firebase refresh_token missing; run: firebase login --reauth")
    return tokens


def refresh_access_token(tokens: dict) -> str:
    expires_at = int(tokens.get("expires_at") or 0)
    if tokens.get("access_token") and expires_at > int(time.time()) + 60:
        return str(tokens["access_token"])

    body = urllib.parse.urlencode(
        {
            "client_id": "563584335869-fgrhgmd47bqnekij2i2bbbctol50ggn.apps.googleusercontent.com",
            "client_secret": "j9Ph33fKz0NNWR2EMkGeTSLp",
            "refresh_token": tokens["refresh_token"],
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    access = payload.get("access_token")
    if not access:
        die(f"token refresh failed: {payload}")
    return str(access)


def api(
    access: str,
    method: str,
    url: str,
    payload: dict | None = None,
) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {access}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        die(f"HTTP {exc.code} {method} {url}\n{body}")


def find_zone(access: str) -> tuple[str, str]:
    for project in DNS_PROJECTS:
        url = f"https://dns.googleapis.com/dns/v1/projects/{project}/managedZones"
        try:
            listed = api(access, "GET", url)
        except SystemExit:
            continue
        for zone in listed.get("managedZones") or []:
            dns_name = str(zone.get("dnsName") or "")
            if dns_name.rstrip(".") == "forgesdlc.com":
                return project, str(zone["name"])
    die(
        "forgesdlc.com Cloud DNS zone not found in "
        + ", ".join(DNS_PROJECTS)
        + "; add CNAME manually in Google Domains / Cloud DNS"
    )


def ensure_cname(access: str, project: str, zone: str) -> None:
    record_name = f"{HOSTNAME}."
    listed = api(
        access,
        "GET",
        f"https://dns.googleapis.com/dns/v1/projects/{project}/managedZones/{zone}/rrsets?name={urllib.parse.quote(record_name)}&type=CNAME",
    )
    existing = (listed.get("rrsets") or [{}])[0] if listed.get("rrsets") else None
    if existing and existing.get("type") == "CNAME":
        values = [r.rstrip(".") for r in existing.get("rrdatas") or []]
        if CNAME_TARGET in values:
            print("dns_ok", HOSTNAME, "->", CNAME_TARGET)
            return
        print("dns_update", HOSTNAME, "from", values, "to", CNAME_TARGET)

    change = {
        "additions": [
            {
                "name": record_name,
                "type": "CNAME",
                "ttl": 300,
                "rrdatas": [f"{CNAME_TARGET}."],
            }
        ]
    }
    if existing:
        change["deletions"] = [existing]

    result = api(
        access,
        "POST",
        f"https://dns.googleapis.com/dns/v1/projects/{project}/managedZones/{zone}/changes",
        change,
    )
    print("dns_change", result.get("id"), result.get("status"))


def ensure_firebase_custom_domain(access: str) -> None:
    base = (
        f"https://firebasehosting.googleapis.com/v1beta1/projects/{FIREBASE_PROJECT}"
        f"/sites/{FIREBASE_SITE}/customDomains"
    )
    listed = api(access, "GET", base)
    names = [
        str(item.get("customDomain") or item.get("name", "").split("/")[-1])
        for item in listed.get("customDomains") or []
    ]
    if HOSTNAME in names:
        print("firebase_domain_ok", HOSTNAME)
        return

    created = api(
        access,
        "POST",
        f"{base}?customDomainId={urllib.parse.quote(HOSTNAME, safe='')}",
        {},
    )
    print("firebase_domain_create", created.get("name") or HOSTNAME)


def main() -> int:
    access = refresh_access_token(load_firebase_tokens())
    project, zone = find_zone(access)
    print("dns_zone", project, zone)
    ensure_cname(access, project, zone)
    ensure_firebase_custom_domain(access)
    print("done", f"https://{HOSTNAME}/fleet/ubuntu/install.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
