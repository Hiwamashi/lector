# Paperless-REST-Client

**Modul:** `app/paperless.py` — asynchroner `httpx`-Client für die
[Paperless-ngx-API](https://docs.paperless-ngx.com/api/). Authentifizierung per API-Token
(`Authorization: Token <token>`).

## Lesen

- `resolve_document_type_id(name)` — Dokumententyp-Name → ID (`/api/document_types/`).
- `list_documents(document_type_id=…, tag_ids=…)` — gefilterte, paginierte Dokumentliste
  (`/api/documents/?document_type__id=…&tags__id__all=…`). Folgt `next`-Links automatisch.
- `get_document(id)` / `get_correspondent_name(id)`.
- `download_original(id)` — Originaldatei + Dateiname (`/api/documents/{id}/download/?original=true`).

`PaperlessDocument` bündelt `id, title, content (OCR-Text), correspondent_id,
document_type_id, tag_ids, custom_fields, original_file_name`.

## Zurückschreiben

- `ensure_custom_field(name, data_type)` / `ensure_tag(name)` — ID holen, bei Bedarf anlegen.
- `set_custom_fields(id, {field_id: value})` — **merge-sicher**: liest bestehende Werte, fügt
  die eigenen hinzu, PATCHt die Gesamtliste (Paperless ersetzt sonst alle Felder).
- `add_tags(id, [tag_ids])` — vereinigt mit bestehenden Tags (kein Überschreiben).
- `add_note(id, text)` — Notiz/Kommentar (`/api/documents/{id}/notes/`).

## Fallstricke

- `set_custom_fields` muss bestehende Felder mitschicken, sonst gehen sie verloren.
- Der Client ist ein Async-Context-Manager (`async with PaperlessClient(...) as c:`).
