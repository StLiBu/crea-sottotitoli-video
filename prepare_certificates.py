from __future__ import annotations

import ssl
from pathlib import Path


root = Path(__file__).resolve().parent
cache = root / "_cache"
cache.mkdir(exist_ok=True)
certificates: list[str] = []
seen: set[bytes] = set()
for store in ("ROOT", "CA"):
    try:
        entries = ssl.enum_certificates(store)
    except (OSError, ssl.SSLError):
        continue
    for der, encoding, _trust in entries:
        if encoding == "x509_asn" and der not in seen:
            seen.add(der)
            certificates.append(ssl.DER_cert_to_PEM_cert(der))

if not certificates:
    raise SystemExit("Non riesco a leggere i certificati fidati di Windows.")

bundle = cache / "windows-ca-bundle.pem"
bundle.write_text("\n".join(certificates), encoding="ascii")
print(bundle)
