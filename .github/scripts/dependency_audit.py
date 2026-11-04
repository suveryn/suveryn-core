"""Known vulnerabilities in the locked Python dependencies (pip-audit), failing CI on any.

    uv export --all-packages --no-dev --no-hashes --format requirements-txt -q | grep -v '^-e' > reqs.txt
    uvx pip-audit -r reqs.txt --no-deps --disable-pip --format json -o audit.json
    python3 .github/scripts/dependency_audit.py audit.json

No dependency was watched before: Pillow sat at 12.3 with a dozen published decoder bugs for weeks
(audit of 4 November 2026). Every advisory fails the job, except those in ``KNOWN``: each names the
package, the versions it applies to, and why it is tolerated for now. An entry stops applying by itself
once the package moves past those versions, and should then be deleted.
"""

import json
import sys

# package -> (applies while the version starts with one of these, why it is tolerated for now)
KNOWN = {
    "pillow": (("12.",), "Docling 2.135 caps Pillow below 13. The avatar decoder no longer reaches any reader but "
                         "PNG, JPEG and WebP (avatars.py), and the document reader runs sandboxed; the move to "
                         "Pillow 13 comes with Docling 2.146 in its own PR."),
}


def main(path: str) -> int:
    report = json.load(open(path, encoding="utf-8"))
    failing, tolerated = [], []
    for dep in report.get("dependencies", []):
        vulns = dep.get("vulns") or []
        if not vulns:
            continue
        name, version = dep["name"].lower(), dep["version"]
        known = KNOWN.get(name)
        line = f"{name} {version}: {len(vulns)} advisories ({', '.join(v['id'] for v in vulns[:3])}{', …' if len(vulns) > 3 else ''}); fixed in {', '.join(sorted({f for v in vulns for f in v.get('fix_versions', [])})) or 'no release yet'}"
        if known and version.startswith(known[0]):
            tolerated.append(f"{line}\n    tolerated: {known[1]}")
        else:
            failing.append(line)
    for line in tolerated:
        print(f"known   {line}")
    for line in failing:
        print(f"::error::{line}")
    print(f"{len(failing)} package(s) with advisories to fix, {len(tolerated)} tolerated for now")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
