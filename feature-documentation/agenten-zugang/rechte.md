# Rechte der Agents in Paperless

Alle Grenzen des Agenten-Zugangs setzt Paperless durch. Der MCP-Server bietet zwar auch
Lösch-, Benutzer-, Mail-Regel- und Workflow-Tools an, ohne die passenden Paperless-Rechte
schlagen diese Aufrufe aber fehl.

## Benutzer und Gruppe

| Benutzer | Client | Eigenschaften |
|---|---|---|
| `agent-claudeai` | claude.ai | Mitglied `agents`, nicht Superuser, nicht Staff |
| `agent-claudecode` | Claude Code | dto. |
| `agent-n8n` | n8n | dto. |

Ein Benutzer pro Client, weil Paperless genau einen API-Token pro Benutzer vergibt. So lässt
sich ein Client einzeln sperren, und die Dokumenthistorie zeigt, welcher Agent etwas geändert
hat. Rechte werden **nur über die Gruppe** vergeben, nie direkt am Benutzer.

Token erzeugen: als Admin in der Benutzerverwaltung bzw. als der Benutzer unter
*Profil → API-Token*. Tokens gehören nur in die Client-Konfiguration, nie ins Repository.

## Rechte der Gruppe `agents` (Stufe 2)

| Bereich | Ansehen | Hinzufügen | Ändern | Löschen |
|---|---|---|---|---|
| Dokumente | ✓ | – | ✓ | – |
| Tags, Korrespondenten, Dokumenttypen, Custom Fields | ✓ | ✓ | ✓ | – |
| Speicherpfade, Gespeicherte Ansichten | ✓ | – | – | – |
| Notizen | ✓ | ✓ | – | – |
| Benutzer, Gruppen, Mail-Konten, Mail-Regeln, Workflows, Einstellungen, Aufgaben | – | – | – | – |

Die letzte Zeile verhindert, dass ein manipulierter Agent sich mehr Rechte verschafft oder per
Mail-Regel Dokumente umleitet.

## Sichtbarkeit: Objekt-Rechte

Globale Rechte allein reichen nicht. Hat ein Dokument einen Besitzer, sehen es nur der Besitzer
und ausdrücklich freigegebene Benutzer oder Gruppen. Deshalb:

1. **Bestand freigeben:** in der Dokumentliste alles auswählen → *Rechte* → Gruppe `agents`
   *Ansehen* und *Ändern*. Den Besitzer nicht entfernen.
2. **Neue Dokumente:** Workflow „Agents freigeben“, Auslöser *Dokument hinzugefügt* (alle
   Quellen), Aktion *Rechte zuweisen* → Gruppe `agents` *Ansehen* und *Ändern*. Greift auch für
   Ergebnis-PDFs, die Lector über `consume` einliefert.
3. **Einzelnes Dokument verbergen:** am Dokument einen **Besitzer setzen** (z. B. den eigenen
   Benutzer) **und** die Freigabe für `agents` entfernen. Ohne Besitzer bleibt ein Dokument für
   jeden Benutzer mit Leserecht sichtbar, auch ohne Freigabe.

Stand der Einrichtung (2026-10-30, Paperless 2.20.15): Gruppe `agents` (id 1) und die drei
Benutzer angelegt; alle 1560 Dokumente per Massenbearbeitung (`set_permissions`, `merge`)
freigegeben; Workflow „Agents freigeben“ (id 1). Kein Dokument hatte einen Besitzer. Die
Benutzer haben zufällige, nirgends gespeicherte Passwörter; sie sind nur per Token nutzbar.

**Tokens erzeugen** (nur der Admin sieht sie): Django-Admin unter
`https://paperless.<domain>/admin/authtoken/tokenproxy/add/`, Benutzer wählen, speichern; der
Token erscheint in der Liste. Direkt in die Client-Konfiguration übernehmen.

Prüfen, ob die Freigabe greift (Token nicht in die Shell-History schreiben, z. B. per Variable
aus einem Passwortmanager):

    curl -s -H "Authorization: Token $AGENT_TOKEN" \
      "https://paperless.<domain>/api/documents/?page_size=1" | jq .count

Die Zahl muss der Gesamtzahl der Dokumente entsprechen (abzüglich bewusst verborgener).

## Einen Client sperren

Token des betroffenen `agent-*`-Benutzers in Paperless widerrufen bzw. neu erzeugen oder den
Benutzer deaktivieren. Die anderen Clients sind nicht betroffen.

## Prüfergebnisse der Grenzen

Mit einem Agent-Token direkt gegen die Paperless-API geprüft (Aufgabe 2.4 des Changes
`paperless-mcp-anbindung`) am 2026-10-30, Paperless 2.20.15, Token von `agent-claudecode`.
Verbotene Aktionen wurden nur gegen Testobjekte, nicht existierende IDs oder als No-op
ausgeführt.

| Aktion | Erwartet | Ergebnis |
|---|---|---|
| Dokumente lesen | erlaubt | ✅ 200, alle 1560 sichtbar |
| Tag anlegen, an Dokument setzen, wieder entfernen | erlaubt | ✅ 201 / 200 / 200 |
| Tag löschen (Test-Tag) | abgelehnt | ✅ 403 |
| Dokument löschen (`DELETE`, nicht existierende ID) | abgelehnt | ✅ 403 (Rechteprüfung vor Objektsuche) |
| Bulk-Löschen (nicht existierende ID) | abgelehnt | ⚪ nicht aussagekräftig (400, Validierung vor Rechteprüfung); globales Löschrecht fehlt |
| Benutzer anlegen, Gruppe anlegen, Benutzerliste lesen | abgelehnt | ✅ 403 |
| Mail-Regel anlegen, Workflow anlegen | abgelehnt | ✅ 403 |
| Dokument hochladen | abgelehnt | ✅ 403 |
| Rechte eines Dokuments setzen (`bulk_edit` `set_permissions`, No-op) | abgelehnt | ❌ **200 — erlaubt** |
| `bulk_edit` mit `delete_pages` | zu klären | nicht ausgeführt, siehe unten |

**Abweichung:** Paperless behandelt Dokumente **ohne Besitzer** so, dass jeder Benutzer mit
Ändern-Recht auch deren Rechte und Besitzer setzen darf. Ein Agent könnte sich damit zum
Besitzer machen oder Freigaben entfernen. Dieselbe Besitzer-Prüfung gilt nach unserem
Verständnis für die PDF-Bearbeitung (`delete_pages`, `rotate`, `merge`); sie ist bei
besitzerlosen Dokumenten vermutlich ebenfalls erlaubt.

**Entscheidung (2026-10-30): bewusst akzeptiert.** Die Agents nutzt ausschließlich der
Anwender selbst; die Dokumente bleiben ohne Besitzer. Gegenmaßnahmen: die betreffenden Tools in
claude.ai blockieren (`bulk_edit_documents`, `bulk_set_object_permissions`, siehe
[clients.md](clients.md)); in Claude Code und n8n ändernde Tool-Aufrufe nicht pauschal
freigeben. Falls später weitere Personen Agents nutzen: allen Dokumenten einen Besitzer geben
(Admin-Konto) und den Workflow um *Besitzer zuweisen* ergänzen — dann sind diese Aktionen für
Agents als Nicht-Besitzer gesperrt.
