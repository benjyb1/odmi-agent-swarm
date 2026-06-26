"""Portal visibility audit: classify every ODMI national portal by how
reachable its metadata is to a static HTTP retriever, and auto-discover a
machine API where one exists.

Read-only network probe. No swarm, no DB. Motivated by the Albania finding
(docs/LANGUAGE_FRAMEWORK_DEEPDIVE.md section F): opendata.gov.al is an Angular
SPA invisible to static retrieval but backed by a documented DCAT API. This
script generalises that check to all 36 portals so the catalogue route gap is
mapped rather than discovered one country at a time.

Classes:
  static-ok : server-rendered HTML, trafilatura/search can read it
  spa       : client-rendered shell, needs an API or a browser render
  waf       : firewall challenge / 403, needs a browser or residential egress
  dead      : unreachable after retries

API discovery probes (first JSON-ish hit wins):
  swagger   : /swagger/v1/swagger.json
  ckan      : /api/3/action/package_search?rows=0
  dcat-json : /data.json, /dcat3.jsonld, /dcat2.jsonld
  dcat-xml  : /catalog.xml

Usage:
  uv run python evaluation/portal_visibility_audit.py
  writes evaluation/results/portal_visibility.json and prints a table.
"""
from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
COORD = ROOT / "scripts" / "run_coordinator.py"
ROUTES_DIR = ROOT / "data" / "catalogue" / "portals"
OUT = ROOT / "evaluation" / "results" / "portal_visibility.json"

HELD_OUT = {"BA", "MK", "ME", "BG", "FI", "HR", "SE", "BE"}
DEV = {"NL", "MT", "NO", "FR", "AL"}

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
_UA = {"User-Agent": "Mozilla/5.0 (ODMI portal-visibility audit; research)"}

_WAF_MARKERS = ("incapsula", "request unsuccessful", "cf-chl", "cloudflare",
                "attention required", "access denied", "captcha")
_SPA_MARKERS = ('id="root"', 'id="app"', "__next", "__nuxt", "ng-version",
                "data-critters", "ng-app", "window.__")


def portals() -> dict[str, dict]:
    src = COORD.read_text(encoding="utf-8")
    body = re.search(r"COUNTRIES\s*=\s*\{(.*?)\n\}", src, re.S).group(1)
    out = {}
    for cc, lang, url in re.findall(
        r'"([A-Z]{2})":\s*\{[^}]*?country_language":\s*"([a-z]{2})"[^}]*?portal_url":\s*"([^"]+)"',
        body, re.S,
    ):
        out[cc] = {"language": lang, "portal_url": url}
    return out


def fetch(url: str, timeout: int = 20, retries: int = 2) -> tuple[int | None, bytes, str]:
    last = ""
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
                return r.getcode(), r.read(400_000), ""
        except urllib.error.HTTPError as e:
            return e.code, (e.read(20_000) if hasattr(e, "read") else b""), f"http {e.code}"
        except Exception as e:  # noqa: BLE001
            last = type(e).__name__
    return None, b"", last


def visible_chars(html: str) -> int:
    no_sc = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    return len(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", no_sc)).strip())


def classify(code, body: bytes) -> tuple[str, dict]:
    html = body.decode("utf-8", "replace")
    low = html.lower()
    vis = visible_chars(html)
    js = len(re.findall(r"<script[^>]+src=", html, re.I))
    meta = {"http": code, "visible_chars": vis, "js_bundles": js}
    if code is None:
        return "dead", meta
    marker = any(m in low for m in _WAF_MARKERS)
    # A real challenge page is short. A long readable page that merely mentions
    # "cloudflare" (a CDN many working portals sit behind) is not WAF-blocked,
    # so require a small body before trusting the marker.
    if code == 403 or (marker and vis < 1500):
        return "waf", meta
    if vis < 600 and (js >= 1 or any(m in low for m in _SPA_MARKERS)):
        return "spa", meta
    return "static-ok", meta


def discover_api(base: str) -> dict | None:
    base = base.rstrip("/")
    probes = [
        ("swagger", "/swagger/v1/swagger.json"),
        ("ckan", "/api/3/action/package_search?rows=0"),
        ("dcat-json", "/data.json"),
        ("dcat-json", "/dcat3.jsonld"),
        ("dcat-json", "/dcat2.jsonld"),
        ("dcat-xml", "/catalog.xml"),
    ]
    for kind, ep in probes:
        code, body, _ = fetch(base + ep, timeout=12, retries=1)
        if code != 200 or not body:
            continue
        head = body[:200].lstrip()
        looks_json = head[:1] in (b"{", b"[")
        if kind == "swagger" and (looks_json or b"swagger" in body[:300].lower()):
            return {"kind": kind, "endpoint": ep}
        if kind == "ckan" and looks_json and b'"success"' in body[:300]:
            return {"kind": kind, "endpoint": ep}
        if kind == "dcat-json" and looks_json and (b"dcat" in body[:2000].lower() or b"dataset" in body[:2000].lower()):
            return {"kind": kind, "endpoint": ep}
        if kind == "dcat-xml" and head[:1] == b"<" and b"atalog" in body[:2000]:
            return {"kind": kind, "endpoint": ep}
    return None


def main() -> int:
    routed = {p.stem for p in ROUTES_DIR.glob("*.json")}
    ps = portals()
    results = {}
    print(f"{'CC':<3}{'role':<10}{'class':<11}{'route?':<8}{'api':<10}{'vis':>7}{'js':>4}  url")
    for cc in sorted(ps):
        url = ps[cc]["portal_url"]
        code, body, err = fetch(url)
        cls, meta = classify(code, body)
        api = discover_api(url) if cls in ("spa", "static-ok", "waf") else None
        role = "DEV" if cc in DEV else ("HELD-OUT" if cc in HELD_OUT else "-")
        has_route = "yes" if cc in routed else "no"
        results[cc] = {
            **ps[cc], "class": cls, "role": role, "has_route": cc in routed,
            "api": api, **meta, "error": err or None,
        }
        api_s = api["kind"] if api else "-"
        print(f"{cc:<3}{role:<10}{cls:<11}{has_route:<8}{api_s:<10}{meta['visible_chars']:>7}{meta['js_bundles']:>4}  {url}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    # Summary: the actionable gap = unrouted portals, split by class.
    unrouted = {cc: r for cc, r in results.items() if not r["has_route"]}
    print(f"\nrouted: {len(results) - len(unrouted)}/{len(results)}")
    print("UNROUTED, by class:")
    for cls in ("static-ok", "spa", "waf", "dead"):
        ccs = [cc for cc, r in unrouted.items() if r["class"] == cls]
        with_api = [cc for cc in ccs if unrouted[cc]["api"]]
        print(f"  {cls:<10} {ccs}  (api discoverable: {with_api})")
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
