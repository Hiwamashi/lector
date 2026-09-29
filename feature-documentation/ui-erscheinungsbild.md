# Erscheinungsbild & Sichtbare Rückmeldung (UI)

**Modul:** `app/static/app.css`, `app/static/app.js` (Markierungslogik)

Die Web-UI ist ein ruhiger, sachlicher „Werkstatt"-Look mit neutralen Grautönen, genau einem Akzent und Ampelfarben ausschließlich für Status. Hell und dunkel sind gleichrangig: Es gibt keinen Standardmodus und keinen Umschalter — die Systemeinstellung des Betriebssystems entscheidet.

## Farbsystem & Token

Alle Farben stehen **ausschließlich** im `:root`-Block in `app.css` (Zeilen 9–36 im Hell-Modus, 43–62 im Dunkel-Modus):

```css
:root {
  --bg, --surface, --surface-alt, --border,
  --ink, --ink-soft,
  --accent, --accent-soft, --accent-ghost, --on-accent,
  --green, --green-bg, --amber, --amber-bg, --red, --red-bg
}
```

**Kritische Regel:** Regeln unterhalb des `:root`-Blocks dürfen **niemals** Hex-Werte verwenden — nur `var(--token)`. Der Dunkel-Modus tauscht nämlich nur die Token-Werte aus, nicht die CSS-Regeln. Ein versteckter Hex-Wert irgendwo in `.class { background: #abc; }` funktioniert im Hell-Modus, zerschießt aber den Dunkel-Modus, ohne dass es auffällt.

### Neue Token in diesem Durchgang

- **`--surface-alt`**: leicht abgesetzte Fläche für Tabellenkopfzeilen, vorher als `#fafbfc` hart verdrahtet. Im Dunkel-Modus (`#20242a`) lesbar von anderen Oberflächen unterscheidbar.
- **`--on-accent`**: Schrift auf gefülltem Akzent. Im Hell-Modus `#ffffff` (weiß), aber im Dunkel-Modus, wo der Akzent aufgehellt wird (`#6cb2d0`), würde Weiß einen Kontrast von 2,4:1 haben — unlesbar. Statt dessen `#0f1417` (sehr dunkel), um den notwendigen Kontrast zu halten.

## Dunkel-Modus

Ausgelöst durch `@media (prefers-color-scheme: dark)` (Zeilen 43–63 in `app.css`). Kein Umschalter, keine ENV-Variable — die Betriebssystem-Einstellung des Nutzers wird respektiert.

**Farbton-Anpassung:** Der Akzent behält seinen Farbton (~200°), wird aber aufgehellt (`#2f6f8f` → `#6cb2d0`), damit er auf dunklem Grund lesbar bleibt.

**Kontraste (WCAG AA-geprüft):**
- Normaler Text: 13,9:1
- Gedämpfter Text (`--ink-soft`): 6,6:1
- Akzent-Schrift: 7,2:1
- Status-Badges: 6,2–6,4:1

**`color-scheme: light dark`** (Zeile 36) im `:root`: Damit Browser-eigene Bedienelemente (Auswahlfelder, Kontrollkästchen, Zahlenfelder, Bildlaufleisten) automatisch im Dunkel-Modus mitziehen statt weiß zu bleiben.

### Sonderregel: GiroCode-QR

Die Klasse `.giro-qr` (Zeilen 218–220) hat eine **feste weiße Fläche** (`background: #ffffff`) in **beiden Modi**. Der QR ist ein Inline-SVG mit dunklen Modulen; auf dunklem Grund wäre er unsichtbar und für eine Banking-App unlesbar, da Scanner eine helle Ruhezone brauchen. Bewusst kein Token hier — der Wert ist hardware-semantisch, nicht gestalterisch.

## Zustände & Interaktionsrückmeldung

### Tastaturbedienung: `:focus-visible`

Zeile 77–81: Statt des unspezifischen `:focus` wird nur `:focus-visible` verwendet. Das heißt: Ein Mausklick auf ein Element zeigt keinen Fokus-Ring, aber die Tabulatortaste tut es. Besser für Nutzer, die mit Maus arbeiten, und korrekt für Tastaturnavigation.

Der Ring liegt **außerhalb** des Elements (`outline-offset: 2px`), sonst verschluckt die Tabellenzelle ihn.

### Taktile Rückmeldung: `:active`

Zeilen 85–89: Tasten und Kacheln verschieben sich um 1 px nach unten (`transform: translateY(1px)`), wenn man sie drückt. Keine Layoutgröße → kein Reflow, nur visuelles Feedback.

### Aktiver Statusfilter: `.tile[aria-current]`

Zeile 126–131: Ein Klick auf eine Statuskachel filtert die Historientabelle. Ohne visuellen Zustand würde die Seite danach unverändert aussehen — nur mit weniger Zeilen. Mit `aria-current="true"` wird die Kachel:
- Mit Akzent-Hintergrund gefüllt
- Der Label wird fett und akzent-farbig
- Auch für Screenreader erkennbar (semantisch, nicht nur optisch)

## Fortschritt in Listenzeilen

Der Fortschrittsbalken (`.progress-inline`, Zeilen 166–176) erscheint **nur** bei `status == "processing"` (siehe Bedingung in `partials/history_rows.html` Zeile 22).

**Begründung:** Der Balken ist das Zeichen dafür, dass gerade etwas passiert. Würde er an jeder Zeile hängen, bliebe diese Aussage nichts übrig. Ein vollständiger, aber unbewegter Balken sieht aus wie eine abgeschlossene Aufgabe — irreführend.

Sein Inhalt ist `aria-hidden="true"` (Zeile 26 in `history_rows.html`), weil daneben die `.progress-inline-text` die aussagekräftige Zahl trägt (z. B. „5/12"). Ein Screenreader würde ohne `aria-hidden` beides vorlesen — zweimal dasselbe Signal.

## Leerzustände

Wenn keine Einträge vorhanden sind, zeigt die Tabelle eine `.empty`-Zeile mit:
- `.empty-title`: kurze Mitteilung (z. B. „Noch nichts eingegangen.")
- `.empty-hint`: ausführlichere Erklärung (z. B. „Sobald eine Datei im überwachten Eingangsordner landet…")

Beide sind in `partials/history_rows.html` (Zeilen 3–7) und `partials/invoice_rows.html` (Zeilen 2–7) definiert und nutzen die Token `--ink` und `--ink-soft` für lesbare Kontraste.

## Bewegung unter `prefers-reduced-motion`

Die Animation `.row-updated` (Keyframes Zeilen 182–185) verblasst eine gerade geänderte Zeile von Akzent-Hintergrund zu transparent. Unter `prefers-reduced-motion: reduce` geschieht das nicht — es würde eine Anfrage nach Bestätigung geben, dass animiert wird.

**Was geschieht trotz `prefers-reduced-motion`:**
- Die Zeile wird trotzdem mit Akzent-Hintergrund **eingefärbt**, bleibt es aber statisch stehen (keine Fade-Out-Animation).
- Nach `FLASH_MS` (1600 ms) wird die Klasse `.row-updated` entfernt, die Farbe verschwindet abrupt.

**Begründung:** Der Zugänglichkeit ist genügt, wenn die Änderung sichtbar wird. Die sanfte Animation ist eine Verfeinerung, keine notwendige Information. Wer Bewegungen reduziert sehen möchte, bekommt die wichtige Information (Hervorhebung) immer noch; sie verschwindet nur ohne Übergang.

(Siehe auch: Aufleuchten geänderter Zeilen in [web-ui-sse.md](web-ui-sse.md#aufleuchten-geänderter-zeilen).)

## Politur-Durchgang (2026-09-29)

Referenz für Gestaltungsregeln ist jetzt `DESIGN.md` im Projektstamm (Leitbild „Das Stellwerk“,
Tokens im Frontmatter). Dieser Durchgang hat nur Mängel behoben, nichts umgestaltet:

- **Seitentitel vereinheitlicht:** `h1` global 1.3rem, `h2` global 1rem. Vorher liefen
  „Rechnungen“, „Empfänger“ und „Paperless nicht erreichbar“ mit der Browser-Größe (2em).
- **Kein Überlaufen mehr:** Dateinamen ohne Leerzeichen brechen um
  (`overflow-wrap: anywhere` an `.history .filename` und `.detail-head h1`). Vorher sprengte
  ein langer Scanner-Name Tabelle und Seite. Jede `.history`-Tabelle liegt in einem
  `.table-scroll`-Wrapper (`overflow-x: auto`) und scrollt darin statt die Seite zu verbreitern;
  bis 720 px behält die Dateinamen-Spalte mindestens 13rem. Bewusst Wrapper statt
  `display: block` an der Tabelle — sonst füllen kurze Tabellen die Breite nicht mehr.
- **Kopfleiste mobil:** bricht um (`flex-wrap`), der Untertitel entfällt bis 720 px.
- **Badges** brechen nicht mehr um (`white-space: nowrap`), z. B. „E-Rechnung“.
- **Neuer Token `--accent-strong`** (hell `#275d78`, dunkel `#86c2dc`): Hover aller gefüllten
  Akzent-Schaltflächen. Stille und deaktivierte Varianten reagieren bewusst nicht.
- **Neue Hinweisvariante `.notice--info`:** Akzent-Hauch, Tinte, Rahmen `--accent-ghost`. Für
  Einrichtungshinweise („Paperless-Sync ist deaktiviert“, „Paperless-Anbindung fehlt“,
  fehlendes Custom Field). Vorher `.alert` in Rot — dort ist aber nichts fehlgeschlagen.
  `.alert` bleibt echten Fehlern vorbehalten.
- **Browser-Bausteine eingefärbt:** `accent-color`, `::selection`, `::file-selector-button`.
- **Tabellenziffern** für die ganze `.history`-Tabelle (Datumsangaben, Seiten, Versuche).
