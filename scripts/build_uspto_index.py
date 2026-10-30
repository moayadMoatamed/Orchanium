"""Build the USPTO precedent index from the raw .rsmi files.

Output (data/uspto/):
  uspto.sqlite   table rxn(id, reactants, agents, product, patent, year, yield_pct)
  product_fp.npy uint64 [N, 16] Morgan r=2 / 1024-bit fingerprints of each main product,
                 row i <-> rxn.id = i
Duplicates (same reaction text after removing atom maps) are dropped."""
from __future__ import annotations

import re
import sqlite3
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "uspto" / "raw"
OUT = ROOT / "data" / "uspto"
_MAP = re.compile(r":\d+\]")
_YIELD = re.compile(r"(\d+(?:\.\d+)?)")
NBITS = 1024


def _parse_yield(*vals: str) -> float | None:
    for v in vals:
        m = _YIELD.search(v or "")
        if m:
            y = float(m.group(1))
            if 0 < y <= 100:
                return y
    return None


def _process(lines: list[str]) -> list[tuple]:
    from rdkit import Chem, RDLogger
    from rdkit.Chem import rdFingerprintGenerator
    RDLogger.DisableLog("rdApp.*")
    gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=NBITS)
    out = []
    for line in lines:
        cols = line.rstrip("\n").split("\t")
        if len(cols) < 6:
            continue
        rxn = _MAP.sub("]", cols[0].split(" ")[0])
        parts = rxn.split(">")
        if len(parts) != 3 or not parts[2]:
            continue
        reactants, agents, products = parts
        mols = [m for m in (Chem.MolFromSmiles(s) for s in products.split(".")) if m is not None]
        if not mols:
            continue
        main = max(mols, key=lambda m: m.GetNumHeavyAtoms())
        if main.GetNumHeavyAtoms() < 4:
            continue
        fp = np.zeros(NBITS // 64, dtype=np.uint64)
        bits = gen.GetFingerprintAsNumPy(main).astype(bool)
        fp[:] = np.packbits(bits, bitorder="little").view(np.uint64)
        out.append((".".join(sorted(reactants.split("."))), agents, Chem.MolToSmiles(main),
                    cols[1], int(cols[3]) if cols[3].isdigit() else None,
                    _parse_yield(cols[4], cols[5]), fp.tobytes()))
    return out


def _chunks(path: Path, size: int = 5000):
    with open(path, encoding="utf-8", errors="replace") as f:
        next(f)                                     # header
        buf = []
        for line in f:
            buf.append(line)
            if len(buf) == size:
                yield buf
                buf = []
        if buf:
            yield buf


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    db_path = OUT / "uspto.sqlite"
    db_path.unlink(missing_ok=True)
    db = sqlite3.connect(db_path)
    db.execute("CREATE TABLE rxn (id INTEGER PRIMARY KEY, reactants TEXT, agents TEXT, product TEXT, "
               "patent TEXT, year INTEGER, yield_pct REAL)")
    seen: set[int] = set()
    fps: list[bytes] = []
    t0, n_in = time.time(), 0
    with Pool() as pool:
        for path in sorted(RAW.glob("*.rsmi")):
            for rows in pool.imap(_process, _chunks(path), chunksize=4):
                batch = []
                for r in rows:
                    n_in += 1
                    h = hash((r[0], r[2]))
                    if h in seen:
                        continue
                    seen.add(h)
                    batch.append((len(fps),) + r[:6])
                    fps.append(r[6])
                db.executemany("INSERT INTO rxn VALUES (?,?,?,?,?,?,?)", batch)
                if len(fps) % 200_000 < len(batch):
                    print(f"  {path.name}: {n_in:,} parsed, {len(fps):,} unique, {time.time() - t0:.0f}s", flush=True)
    db.execute("CREATE INDEX idx_product ON rxn(product)")
    db.commit()
    arr = np.frombuffer(b"".join(fps), dtype=np.uint64).reshape(-1, NBITS // 64)
    np.save(OUT / "product_fp.npy", arr)
    print(f"done: {len(fps):,} unique reactions from {n_in:,} rows in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
