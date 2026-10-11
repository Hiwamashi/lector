# Spec Delta

## REMOVED Requirements

### Requirement: Der Dienst verlangt keine Authentifizierung

**Reason**: Lector soll auch öffentlich erreichbar hinter einem HTTPS-Proxy betrieben werden
können. Der Zugang zur Weboberfläche wird deshalb von der neuen Capability `web-zugang`
geregelt, die eine Anmeldung über Paperless anbietet. Eine eigene Benutzerverwaltung bringt
der Dienst weiterhin nicht mit.

**Migration**: Der bisherige anmeldefreie Betrieb bleibt der Standard (`AUTH_MODE=none`,
siehe `web-zugang`). Bestehende Installationen müssen nichts tun. Wer die Anmeldung über
Paperless nutzen will, setzt `AUTH_MODE=paperless` und `PAPERLESS_URL`.
