"""Download and unpack the USPTO reaction SMILES files (Lowe, CC0) from Figshare
into data/uspto/raw. Only the two SMILES archives (~163 MB) are fetched."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import py7zr

ARTICLE = "https://api.figshare.com/v2/articles/5104873"
WANTED = ("1976_Sep2016_USPTOgrants_smiles.7z", "2001_Sep2016_USPTOapplications_smiles.7z")
RAW = Path(__file__).resolve().parents[1] / "data" / "uspto" / "raw"


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    files = {f["name"]: f for f in httpx.get(ARTICLE, timeout=30).json()["files"]}
    for name in WANTED:
        f = files[name]
        dest = RAW / name
        if not dest.exists() or dest.stat().st_size != f["size"]:
            print(f"downloading {name} ({f['size'] / 1e6:.0f} MB)", flush=True)
            with httpx.stream("GET", f["download_url"], follow_redirects=True, timeout=None) as r:
                r.raise_for_status()
                with open(dest, "wb") as out:
                    for chunk in r.iter_bytes(1 << 20):
                        out.write(chunk)
        print(f"extracting {name}", flush=True)
        with py7zr.SevenZipFile(dest) as z:
            z.extractall(RAW)
    for p in sorted(RAW.rglob("*")):
        if p.is_file():
            print(f"  {p.relative_to(RAW)}  {p.stat().st_size / 1e6:.0f} MB")


if __name__ == "__main__":
    sys.exit(main())
