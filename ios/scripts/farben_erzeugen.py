#!/usr/bin/env python3
"""Erzeugt die Color Sets der App aus den Farbwerten von DESIGN.md (hell / dunkel).

Quelle der Wahrheit ist das Front-Matter von DESIGN.md im Repo-Root. Die Hex-Werte stehen nur
hier und im erzeugten Asset-Katalog, nie im Swift-Code (dort nur über `Farbe`).

Aufruf (aus dem Repo-Root, ohne Fremdpakete):
    python3 ios/scripts/farben_erzeugen.py
"""
import json
from pathlib import Path

IOS = Path(__file__).resolve().parent.parent
KATALOG = IOS / "Lector" / "Design" / "Farben.xcassets"
AKZENT = IOS / "Lector" / "Assets.xcassets" / "AccentColor.colorset"

# Assetname -> (hell, dunkel) laut DESIGN.md
ROLLEN = {
    "akzent":        ("#2f6f8f", "#6cb2d0"),  # primary
    "akzentAuf":     ("#ffffff", "#0f1417"),  # on-primary
    "akzentHauch":   ("#e8f0f4", "#16303c"),  # primary-soft
    "textLeise":     ("#5b636b", "#9aa3ab"),  # neutral-ink-soft
    "gruen":         ("#2e7d4f", "#5cbf87"),  # signal-green
    "gruenFlaeche":  ("#e6f4ec", "#17301f"),
    "amber":         ("#b9770e", "#e0a33c"),  # signal-amber
    "amberFlaeche":  ("#fbf0db", "#38290f"),
    "rot":           ("#b3261e", "#f08a80"),  # signal-red
    "rotFlaeche":    ("#fbe6e4", "#3a1c1a"),
    "violett":       ("#6b4d9e", "#b49ae0"),  # signal-violet
    "violettFlaeche": ("#efeaf8", "#2a2140"),
}


def komponenten(hexwert):
    r, g, b = (int(hexwert[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return {"red": f"{r:.4f}", "green": f"{g:.4f}", "blue": f"{b:.4f}", "alpha": "1.000"}


def colorset(hell, dunkel):
    return {
        "colors": [
            {
                "color": {"color-space": "srgb", "components": komponenten(hell)},
                "idiom": "universal",
            },
            {
                "color": {"color-space": "srgb", "components": komponenten(dunkel)},
                "idiom": "universal",
                "appearances": [{"appearance": "luminosity", "value": "dark"}],
            },
        ],
        "info": {"author": "xcode", "version": 1},
    }


def schreiben(ordner, inhalt):
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "Contents.json").write_text(json.dumps(inhalt, indent=2) + "\n")


def main():
    info = {"info": {"author": "xcode", "version": 1}}
    (KATALOG).mkdir(parents=True, exist_ok=True)
    (KATALOG / "Contents.json").write_text(json.dumps(info, indent=2) + "\n")
    for name, (hell, dunkel) in ROLLEN.items():
        schreiben(KATALOG / f"{name}.colorset", colorset(hell, dunkel))
    # Globale Akzentfarbe der App (Tint, Schaltflächen): Werkstatt-Petrol.
    (IOS / "Lector" / "Assets.xcassets").mkdir(parents=True, exist_ok=True)
    assets = IOS / "Lector" / "Assets.xcassets"
    (assets / "Contents.json").write_text(json.dumps(info, indent=2) + "\n")
    schreiben(AKZENT, colorset(*ROLLEN["akzent"]))
    print(f"{len(ROLLEN)} Color Sets in {KATALOG}")


if __name__ == "__main__":
    main()
