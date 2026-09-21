# Spec Delta

## ADDED Requirements

### Requirement: Bewahrte Zwischenergebnisse werden freigegeben, sobald sie entbehrlich sind

Der Dienst MUSS die bewahrten Blockergebnisse eines Vorgangs entfernen, sobald dieser einen
Endzustand erreicht — gleich welchen. Sie dienen ausschließlich dem Wiederholversuch; nach
`done`, `skipped_erechnung` oder `failed` gibt es keinen mehr.

Zusätzlich MUSS der Dienst Zwischenergebnisse entfernen, die älter als
`CHUNK_CACHE_RETENTION_DAYS` (Standard 7) sind, damit Reste eines abgebrochenen Laufs nicht
dauerhaft liegen bleiben. Ein Wert kleiner oder gleich 0 schaltet dieses Verfallen ab.

Das Entfernen DARF weder den Vorgang noch seinen Verlauf antasten: Die Historie bleibt
vollständig erhalten.

#### Scenario: Vorgang erfolgreich abgeschlossen

- **WHEN** ein Dokument vollständig veredelt und abgelegt wurde
- **THEN** sind seine bewahrten Blockergebnisse entfernt, während Vorgang und Verlauf
  unverändert abrufbar bleiben

#### Scenario: Vorgang endgültig gescheitert

- **WHEN** ein Vorgang seinen letzten Versuch verbraucht hat und auf `failed` steht
- **THEN** sind seine bewahrten Blockergebnisse entfernt

#### Scenario: Wiederholversuch eingeplant

- **WHEN** ein Vorgang gescheitert ist, aber ein Wiederholversuch eingeplant wurde
- **THEN** bleiben seine bewahrten Blockergebnisse erhalten — sie werden gerade dann
  gebraucht

#### Scenario: Rest eines abgebrochenen Laufs

- **WHEN** Zwischenergebnisse älter als die Verfallsfrist sind
- **THEN** werden sie entfernt, auch wenn der zugehörige Vorgang keinen Endzustand erreicht
  hat

#### Scenario: Verfallen abgeschaltet

- **WHEN** `CHUNK_CACHE_RETENTION_DAYS` auf 0 oder kleiner steht
- **THEN** verfallen Zwischenergebnisse nicht von selbst, werden aber weiterhin bei Erreichen
  eines Endzustands entfernt
