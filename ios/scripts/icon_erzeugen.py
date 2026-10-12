#!/usr/bin/env python3
"""Erzeugt das vorläufige App-Symbol (1024x1024, ohne Alpha): weißes „L“ auf Werkstatt-Petrol.

Platzhalter bis ein richtiges Symbol entworfen ist (offene Frage im Design). Ohne Fremdpakete:
    python3 ios/scripts/icon_erzeugen.py
"""
import json
import struct
import zlib
from pathlib import Path

ZIEL = Path(__file__).resolve().parent.parent / "Lector" / "Assets.xcassets" / "AppIcon.appiconset"
GROESSE = 1024
PETROL = (0x2F, 0x6F, 0x8F)  # primary aus DESIGN.md
WEISS = (0xFF, 0xFF, 0xFF)


def ist_l(x, y):
    # Senkrechter Balken und Fuß des „L“.
    senkrecht = 330 <= x < 480 and 250 <= y < 774
    fuss = 330 <= x < 700 and 624 <= y < 774
    return senkrecht or fuss


def png():
    zeilen = bytearray()
    for y in range(GROESSE):
        zeilen.append(0)
        for x in range(GROESSE):
            zeilen.extend(WEISS if ist_l(x, y) else PETROL)

    def chunk(art, daten):
        rumpf = art + daten
        return struct.pack(">I", len(daten)) + rumpf + struct.pack(">I", zlib.crc32(rumpf))

    kopf = struct.pack(">IIBBBBB", GROESSE, GROESSE, 8, 2, 0, 0, 0)
    daten = zlib.compress(bytes(zeilen), 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", kopf) + chunk(b"IDAT", daten) + chunk(b"IEND", b"")


def main():
    ZIEL.mkdir(parents=True, exist_ok=True)
    (ZIEL / "AppIcon.png").write_bytes(png())
    inhalt = {
        "images": [{
            "filename": "AppIcon.png", "idiom": "universal",
            "platform": "ios", "size": "1024x1024",
        }],
        "info": {"author": "xcode", "version": 1},
    }
    (ZIEL / "Contents.json").write_text(json.dumps(inhalt, indent=2) + "\n")
    print(f"Symbol in {ZIEL}")


if __name__ == "__main__":
    main()
