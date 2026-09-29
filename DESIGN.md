---
name: Lector
description: OCR-Veredelung für Paperless — ruhiger Leitstand, der nur spricht, wenn es etwas zu melden gibt.
colors:
  primary: "#2f6f8f"
  primary-strong: "#275d78"
  primary-soft: "#e8f0f4"
  primary-ghost: "rgba(47, 111, 143, 0.5)"
  on-primary: "#ffffff"
  neutral-bg: "#f4f5f6"
  neutral-surface: "#ffffff"
  neutral-surface-alt: "#fafbfc"
  neutral-border: "#e2e5e8"
  neutral-ink: "#1f2328"
  neutral-ink-soft: "#5b636b"
  signal-green: "#2e7d4f"
  signal-green-bg: "#e6f4ec"
  signal-amber: "#b9770e"
  signal-amber-bg: "#fbf0db"
  signal-red: "#b3261e"
  signal-red-bg: "#fbe6e4"
  signal-violet: "#6b4d9e"
  signal-violet-bg: "#efeaf8"
  qr-white: "#ffffff"
  primary-dark: "#6cb2d0"
  primary-strong-dark: "#86c2dc"
  primary-soft-dark: "#16303c"
  on-primary-dark: "#0f1417"
  neutral-bg-dark: "#14171a"
  neutral-surface-dark: "#1a1d21"
  neutral-surface-alt-dark: "#20242a"
  neutral-border-dark: "#2b3036"
  neutral-ink-dark: "#e6e9ec"
  neutral-ink-soft-dark: "#9aa3ab"
  signal-green-dark: "#5cbf87"
  signal-green-bg-dark: "#17301f"
  signal-amber-dark: "#e0a33c"
  signal-amber-bg-dark: "#38290f"
  signal-red-dark: "#f08a80"
  signal-red-bg-dark: "#3a1c1a"
  signal-violet-dark: "#b49ae0"
  signal-violet-bg-dark: "#2a2140"
typography:
  display:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "1.8rem"
    fontWeight: 700
    lineHeight: 1.5
  headline:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "1.3rem"
    fontWeight: 700
  title:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "1rem"
    fontWeight: 700
  body:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "0.9rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "0.85rem"
    fontWeight: 400
  badge:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "0.78rem"
    fontWeight: 600
rounded:
  sm: "6px"
  md: "8px"
  lg: "10px"
  pill: "999px"
spacing:
  xs: "0.25rem"
  sm: "0.5rem"
  md: "0.75rem"
  lg: "1rem"
  xl: "1.5rem"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.md}"
    padding: "0.5rem 0.9rem"
    typography: "{typography.body}"
  button-primary-hover:
    backgroundColor: "{colors.primary-strong}"
    textColor: "{colors.on-primary}"
  button-primary-disabled:
    backgroundColor: "{colors.neutral-ink-soft}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.md}"
  button-quiet:
    backgroundColor: "{colors.neutral-surface}"
    textColor: "{colors.neutral-ink}"
    rounded: "{rounded.md}"
    padding: "0.5rem 0.9rem"
  input:
    backgroundColor: "{colors.neutral-surface}"
    textColor: "{colors.neutral-ink}"
    rounded: "{rounded.md}"
    padding: "0.5rem 0.7rem"
    typography: "{typography.body}"
  card:
    backgroundColor: "{colors.neutral-surface}"
    rounded: "{rounded.lg}"
    padding: "1rem"
  status-tile:
    backgroundColor: "{colors.neutral-surface}"
    textColor: "{colors.neutral-ink}"
    rounded: "{rounded.lg}"
    padding: "1rem"
  status-tile-active:
    backgroundColor: "{colors.primary-soft}"
    textColor: "{colors.primary}"
  badge-done:
    backgroundColor: "{colors.signal-green-bg}"
    textColor: "{colors.signal-green}"
    rounded: "{rounded.pill}"
    padding: "0.15rem 0.6rem"
    typography: "{typography.badge}"
  badge-pending:
    backgroundColor: "{colors.signal-amber-bg}"
    textColor: "{colors.signal-amber}"
    rounded: "{rounded.pill}"
    padding: "0.15rem 0.6rem"
  badge-failed:
    backgroundColor: "{colors.signal-red-bg}"
    textColor: "{colors.signal-red}"
    rounded: "{rounded.pill}"
    padding: "0.15rem 0.6rem"
  badge-blocked:
    backgroundColor: "{colors.signal-violet-bg}"
    textColor: "{colors.signal-violet}"
    rounded: "{rounded.pill}"
    padding: "0.15rem 0.6rem"
  badge-processing:
    backgroundColor: "{colors.primary-soft}"
    textColor: "{colors.primary}"
    rounded: "{rounded.pill}"
    padding: "0.15rem 0.6rem"
  nav-link:
    textColor: "{colors.neutral-ink-soft}"
    typography: "{typography.body}"
  nav-link-hover:
    textColor: "{colors.primary}"
---

# Design System: Lector

## Overview

**Creative North Star: "Das Stellwerk"**

Lector ist ein Leitstand, kein Schaufenster. Die Fläche ist ruhig und neutral wie ein
Stellpult im Normalbetrieb; die Signallampen — Grün, Amber, Rot, Violett — leuchten nur
dort, wo ein Zustand gemeldet werden muss. Wer die Seite öffnet, soll mit einem Blick über
die Status-Kacheln wissen, ob alles durchgelaufen ist, und erst bei einem Signal tiefer
einsteigen: Historie, Detailansicht, Verlaufs-Log.

Die Dichte ist mittel und auf den Desktop ausgelegt: Tabellen in 0,9 rem, Karten mit
1 rem Innenabstand, ein Inhaltsband von höchstens 1100 px. Es gibt genau einen Akzent,
Werkstatt-Petrol, für Handlungen und „läuft gerade". Bewegung ist knapp und trägt immer
eine Information — ein Fortschrittsbalken, ein kurzes Aufleuchten einer aktualisierten
Zeile, ein Puls an der Füllkante eines laufenden Batch-Laufs. Hell- und Dunkelmodus sind
gleichrangig; das Betriebssystem entscheidet, es gibt keinen Umschalter.

Ausdrücklich abgelehnt: der SaaS-Marketing-Look (Verläufe als Dekor, Glas-Effekte,
Riesen-Hero-Zahlen, bunte Illustrationen) und eine Nachbildung von Paperless-ngx. Lector
ist als eigenständiger Vorschritt erkennbar, nicht als Paperless-Unterseite.

**Key Characteristics:**
- Ein Akzent, vier Signalfarben, sonst Graustufen.
- Status wird über Farbe **und** Beschriftung transportiert, nie über Farbe allein.
- Flache Karten mit Haarlinie und kaum sichtbarem Schatten.
- Systemschrift, keine Webfonts, keine externen Ressourcen.
- Bewegung nur als Zustandsmeldung, mit `prefers-reduced-motion`-Ersatz.

## Colors

Neutrales Grau als Pult, Werkstatt-Petrol als einziges Bedienlicht, Ampelfarben
ausschließlich als Signal.

### Primary
- **Werkstatt-Petrol** (`primary`; dunkel `primary-dark`): gefüllte Schaltflächen, Links,
  Hover-Rahmen, Fokusring, Fortschrittsfüllung, „in Arbeit" und „E-Rechnung
  durchgereicht". Im Dunkelmodus behält er den Farbton (~200°) und wird nur aufgehellt.
- **Petrol tief** (`primary-strong`; dunkel `primary-strong-dark`): Hover-Zustand gefüllter
  Schaltflächen. Gleicher Farbton, eine Stufe tiefer (im Dunkelmodus heller).
- **Petrol-Hauch** (`primary-soft`): Fläche der aktiven Status-Kachel, des
  Live-Hinweises und des Aufleuchtens geänderter Zeilen.
- **Petrol-Schleier** (`primary-ghost`): halbtransparente Überlagerung, nur für den Puls
  an der Füllkante des Batch-Balkens.
- **Schrift auf Petrol** (`on-primary`; dunkel `on-primary-dark`): Weiß im Hellmodus,
  fast Schwarz im Dunkelmodus — weil Weiß auf dem aufgehellten Akzent nur 2,4:1 hätte.

### Neutral
- **Pultgrau** (`neutral-bg`): Seitenhintergrund.
- **Tafelweiß** (`neutral-surface`): Karten, Tabellen, Kopfleiste, Eingabefelder.
- **Kopfzeilengrau** (`neutral-surface-alt`): Tabellenköpfe.
- **Haarlinie** (`neutral-border`): Rahmen, Zeilentrenner, leere Fortschrittsbahn.
- **Tinte** (`neutral-ink`): Fließtext und Werte.
- **Bleistift** (`neutral-ink-soft`): Beschriftungen, Zeitstempel, Metadaten, deaktivierte
  Schaltflächen.

### Signal (Statusfarben)
Jede Signalfarbe existiert als Paar aus Schrift-/Linienton und blasser Fläche.
- **Signalgrün** (`signal-green`): erledigt, exportiert, GiroCode bereit.
- **Signalamber** (`signal-amber`): wartet, in der Warteschlange, Vorschlag, unsicher.
- **Signalrot** (`signal-red`): endgültig fehlgeschlagen, Alert-Box.
- **Stellwerk-Violett** (`signal-violet`): „angehalten — wartet auf eine Entscheidung".
  Weder Fehler noch Wartezustand der Reihe; deshalb weder Amber noch Rot.

### Sonderwert
- **QR-Weiß** (`qr-white`): feste weiße Ruhezone hinter dem GiroCode, in beiden Modi.
  Hardware-Semantik (Scanner brauchen hellen Grund), kein Gestaltungstoken.

### Named Rules
**The One Light Rule.** Werkstatt-Petrol ist das einzige Bedienlicht. Keine zweite
Akzentfarbe, keine farbigen Schaltflächen außerhalb von Petrol.

**The Signal-Only Rule.** Grün, Amber, Rot und Violett stehen ausschließlich für Zustände.
Sie schmücken nie, und „etwas ist neu" ist keine Wertung — dafür gilt Petrol.

**The Token-Only Rule.** Unterhalb des `:root`-Blocks in `app/static/app.css` steht kein
einziger Farbwert, nur `var(--token)`. Der Dunkelmodus tauscht ausschließlich Tokenwerte;
jeder verdrahtete Hex-Wert bricht ihn unbemerkt. Einzige Ausnahme: `qr-white`.

## Typography

**Display Font:** system-ui (mit -apple-system, "Segoe UI", Roboto, sans-serif)
**Body Font:** dieselbe Systemschrift

**Character:** Eine einzige Systemschrift, die auf jedem Gerät nach Betriebssystem
aussieht — Werkzeug, nicht Marke. Hierarchie entsteht über Größe und Gewicht, nie über
eine zweite Familie.

### Hierarchy
- **Display** (700, 1.8rem): nur die Zählerwerte der Status-Kacheln. Die laufende Zahl im
  Batch-Lauf nutzt 1.6rem / 650 mit `line-height: 1`.
- **Headline** (700, 1.3rem): jeder Seitentitel (`h1`) — Listen wie Detailansicht.
- **Title** (700, 1rem): Karten- und Abschnittsüberschriften (`h2`: GiroCode, Zahldaten,
  Verlauf).
- **Body** (400, 0.9rem, line-height 1.5): Tabellenzellen, Formularfelder, Navigation,
  Schaltflächen. Seitenbasis ist 1rem, gearbeitet wird in 0.9rem.
- **Label** (400, 0.85rem): Kachelbeschriftungen, `dt`-Metadaten, Verlaufs-Log,
  Leerzustands-Hinweise (max. 46ch).
- **Badge** (600, 0.78rem): Status-Pillen.

**The One-Title Rule.** Es gibt genau eine Titelstufe für Seiten. `h1` und `h2` sind global
auf Headline bzw. Title gesetzt; keine Seite fällt auf die Browser-Größe zurück.

### Named Rules
**The Tabular-Figures Rule.** Jede Zahl, die sich live ändert (Fortschritt, Batch-Zähler,
Legende), setzt `font-variant-numeric: tabular-nums`, damit sie beim Hochzählen nicht
zappelt.

## Layout

Ein zentriertes Inhaltsband (max. 1100px, seitlich 1.5rem) unter einer vollbreiten
Kopfleiste. Die Kopfleiste trägt links Marke und Navigation, rechts den Untertitel
„OCR-Veredelung für Paperless".

- **Status-Kacheln:** Raster mit `repeat(auto-fit, minmax(150px, 1fr))` und 0.75rem Abstand —
  bewusst ohne feste Spaltenzahl, damit neue Zustände nicht gequetscht werden.
- **Werkzeugzeilen** (Filter, Upload, Empfänger-Toolbar): umbrechende Flex-Reihen mit
  0.5rem Abstand; das Suchfeld wächst, mindestens 180px.
- **Metadaten:** zweispaltiges Raster `max-content 1fr`.
- **Verlaufs-Log:** dreispaltig (11rem Zeit · 9rem Ereignis · Rest Nachricht).
- **Rechnungsdetail:** GiroCode-Spalte (220–280px) neben dem Zahldaten-Formular.
- **Rhythmus:** 0.25 / 0.5 / 0.75 / 1 / 1.5rem; Abschnitte trennen sich mit 1rem, große
  Blöcke mit 1.5rem.

**Responsive (≤ 720px):** Kacheln zweispaltig, Verlaufs-Log und Rechnungsdetail
einspaltig, in der Historientabelle fallen Spalte 3 und 5 weg. Desktop ist der Maßstab;
das Handy wird bedient, nicht optimiert. Zusätzlich
entfällt der Untertitel der Kopfleiste, die Navigation bricht unter die Marke, und jede
Tabelle scrollt in sich statt die Seite zu verbreitern (Dateinamen-Spalte min. 13rem).
Lange Dateinamen dürfen überall an beliebiger Stelle umbrechen (`overflow-wrap: anywhere`).

## Elevation & Depth

Fast flach. Tiefe entsteht aus dem Kontrast Pultgrau → Tafelweiß und einer Haarlinie;
der Schatten ist so leise, dass er nur die Kante der Karte andeutet. Es gibt genau eine
Schattenstufe, keine Hover-Anhebung.

### Shadow Vocabulary
- **Tafelkante** (`box-shadow: 0 1px 2px rgba(16, 24, 32, 0.06), 0 2px 8px rgba(16, 24, 32, 0.04)`;
  dunkel `0 1px 2px rgba(0, 0, 0, 0.4), 0 2px 8px rgba(0, 0, 0, 0.3)`): Karten,
  Kacheln, Tabellen, Metadaten, Verlaufs-Log, Batch-Karte.

### Named Rules
**The Flat-Pult Rule.** Oberflächen heben sich nicht. Zustand zeigt sich durch Rahmenfarbe
(Hover → Petrol) oder Füllung (aktiv → Petrol-Hauch, Schatten entfällt), nie durch mehr
Schatten.

## Shapes

Sanft gerundete, rechteckige Formen. Drei Radien, klar zugeordnet: Container 10px,
Bedienelemente 8px, kompakte Inline-Steuerungen 6px. Status-Pillen und Fortschrittsbahnen
sind vollrund (999px). Rahmen sind durchgängig 1px Haarlinie; die einzige dickere Linie
ist die 3px-Signalkante oben an jeder Status-Kachel und die 3px-Kante links am
Live-Hinweis.

## Components

### Buttons
Gefüllt, knapp und bestimmt — ein Druck gibt einen Millimeter nach.
- **Shape:** sanft gerundet (8px).
- **Primary:** Werkstatt-Petrol mit Schrift auf Petrol, 0.5rem × 0.9rem, 0.9rem Schrift.
- **Hover:** Petrol tief, 0.15s Übergang von Hintergrund und Rahmen.
- **Active:** `translateY(1px)` als taktile Rückmeldung, ohne Reflow; entfällt bei
  reduzierter Bewegung.
- **Disabled:** Bleistiftgrau gefüllt, `cursor: not-allowed`.
- **Quiet:** transparent mit Haarlinie und Tinte; für die umkehrbare Nebenhandlung
  (z. B. „Verwerfen" neben „Freigeben", „Abbrechen" im Batch-Lauf — dort färbt Hover den
  Rahmen rot).
- **Link-Button:** textlos-rahmenlos in Petrol, für Inline-Aktionen in Tabellenzellen.

### Status-Kachel (Signature)
Die Signallampe des Stellwerks.
- Tafelweiß, Haarlinie, 10px, 1rem Innenabstand, Tafelkante.
- 3px-Kante oben in der Signalfarbe des Zustands (Petrol für „in Arbeit" und
  „E-Rechnung", Amber, Violett, Grün, Rot; Bleistift als Rückfall).
- Zähler in Display-Stufe, Beschriftung in Label-Stufe.
- **Hover:** Rahmen Petrol. **Aktiv (Filter gesetzt):** `aria-current`, Fläche
  Petrol-Hauch, Rahmen Petrol, Beschriftung Petrol/600, Schatten entfällt.

### Status-Badges
- Vollrunde Pille, 0.15rem × 0.6rem, Badge-Typo.
- Immer Paar aus blasser Signalfläche + kräftigem Signalton; „kein Status" nutzt Pultgrau
  mit Bleistift.

### Cards / Containers
- **Corner Style:** 10px.
- **Background:** Tafelweiß auf Pultgrau.
- **Shadow Strategy:** Tafelkante (siehe Elevation).
- **Border:** 1px Haarlinie.
- **Internal Padding:** 1rem.

### Inputs / Fields
- **Style:** Tafelweiß, 1px Haarlinie, 8px, 0.5rem × 0.7rem, 0.9rem Schrift.
- **Focus:** globaler Fokusring — 2px Petrol, 2px Abstand außerhalb, nur bei
  `:focus-visible`.
- Browser-Bedienelemente ziehen über `color-scheme: light dark` in den Dunkelmodus mit.

### Navigation
- Kopfleiste Tafelweiß mit Haarlinie unten. Marke „▤ Lector" (1.2rem/600, Zeichen in
  Petrol). Links in Bleistift, 0.9rem/500, Hover Petrol, keine Unterstreichung.

### Tabelle (Historie)
- Tafelweiß, 10px, Tafelkante; Kopf in Kopfzeilengrau/Bleistift/600.
- Zellen 0.6rem × 0.8rem, Trenner als Haarlinie. Sortierbare Köpfe mit Pfeil, der erst
  bei aktiver Sortierung voll deckend in Petrol erscheint.
- **Leerzustand:** zentriert, Titel in Tinte/600, Hinweis in Label-Stufe (max. 46ch).
- **Live-Änderung:** Zeile leuchtet 1.6s in Petrol-Hauch auf und verblasst.

### Fortschritt
- **Detail:** 1.4rem hohe, vollrunde Bahn in Haarlinie, Füllung Petrol, Beschriftung
  zentriert darin.
- **Listenzeile:** 3.5rem × 0.4rem Mini-Balken nur bei laufenden Dokumenten — der Balken
  heißt „hier passiert gerade etwas".
- **Batch-Lauf:** eigene Karte; segmentierter Balken (Petrol erledigt, Amber übersprungen,
  Rot fehlgeschlagen) mit Puls an der Füllkante; Zähltext steht neben, nie in dem Balken.

### Hinweise
- **Alert:** Signalrot-Fläche, rote Haarlinie, 8px — nur für endgültige Fehler.
- **Notice blocked / success:** Violett bzw. Grün als Fläche + Linie, mit gewichteten
  Aktionen (Primary + Quiet).
- **Notice info:** Petrol-Hauch mit Petrol-Schleier-Rahmen und Tinte — für
  Einrichtungshinweise („Paperless-Sync ist deaktiviert“). Nichts ist kaputt, deshalb nie Rot.
- **Live-Status:** Petrol-Hauch mit 3px-Kante links — sichtbar, aber nicht alarmierend.

### GiroCode
- QR als Inline-SVG auf fester QR-Weiß-Fläche (max. 240px, 0.6rem Ruhezone, 8px) — in
  beiden Modi hell.

## Do's and Don'ts

### Do:
- **Do** Farben nur als `var(--token)` verwenden und neue Farben immer paarweise für Hell
  und Dunkel im `:root`-Block anlegen.
- **Do** jeden Zustand mit Signalfarbe **und** Text kennzeichnen (Badge-Beschriftung,
  Kachel-Label).
- **Do** Bewegung nur einsetzen, wenn sie einen Zustand meldet, und für
  `prefers-reduced-motion` einen Ersatz vorsehen, der die Information erhält.
- **Do** Nebenhandlungen als Quiet-Button neben die gefüllte Hauptaktion stellen.
- **Do** Kontraste in beiden Modi auf WCAG AA halten (Text 13,9:1, gedämpft 6,6:1,
  Badges ≥ 6,2:1 als Bestandsniveau).
- **Do** Live-Zahlen mit Tabellenziffern setzen; Tabellen setzen sie durchgängig.
- **Do** Browser-Bausteine einfärben: `accent-color`, `::selection` im Petrol-Hauch,
  Dateiauswahl-Knopf im Kopfzeilengrau mit Haarlinie.

### Don't:
- **Don't** Verläufe als Dekor, Glas-Effekte, große Hero-Zahlen oder Illustrationen
  einsetzen — kein SaaS-Marketing-Look.
- **Don't** Paperless-ngx nachbilden (Layout, Farbwelt, Komponenten); Lector bleibt ein
  eigenständiger Vorschritt.
- **Don't** Rot für Konfigurations- oder Einrichtungshinweise verwenden; dafür gilt Notice info.
- **Don't** eine zweite Akzentfarbe oder Signalfarben als Schmuck einführen.
- **Don't** Hex-Werte unterhalb des `:root`-Blocks schreiben (Ausnahme: GiroCode-Ruhezone).
- **Don't** Webfonts, CDNs oder eine Node-Buildchain einführen; das Stylesheet bleibt
  handgeschrieben und offline.
- **Don't** Karten beim Hover anheben oder zusätzliche Schattenstufen erfinden.
- **Don't** einen Hell/Dunkel-Umschalter bauen — das Betriebssystem entscheidet.
