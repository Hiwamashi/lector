import SwiftUI

/// Detail eines Vorgangs: Angaben, Verlauf und bei einem angehaltenen Vorgang die Entscheidung
/// Freigeben oder Verwerfen (mit Bestätigung).
struct DetailAnsicht: View {
    let historie: HistorieModell
    @State private var modell: DetailModell
    @State private var zuBestaetigen: DetailModell.Entscheidung?

    init(dokument: DokumentDTO, client: APIClient, historie: HistorieModell) {
        self.historie = historie
        _modell = State(initialValue: DetailModell(
            dokument: dokument, client: client, aktualisiert: { [historie] neu in await historie.dokumentUebernehmen(neu) }))
    }

    var body: some View {
        let dokument = modell.dokument
        List {
            Section {
                kopf(dokument)
                if let hinweis = modell.hinweis {
                    Fehlerflaeche(text: hinweis, art: .hinweis)
                        .accessibilityIdentifier("detail.hinweis")
                }
                if let fehler = modell.fehler {
                    Fehlerflaeche(text: fehler)
                        .accessibilityIdentifier("detail.fehler")
                }
                if dokument.zustand == .processing, let gesamt = dokument.totalPages, gesamt > 0 {
                    VStack(alignment: .leading, spacing: 4) {
                        ProgressView(value: Double(min(dokument.processedPages, gesamt)), total: Double(gesamt))
                        Text("Seite \(dokument.processedPages) von \(gesamt)").font(.caption).foregroundStyle(.textLeise)
                    }
                }
                if dokument.zustand == .failed { gescheitert(dokument) }
                if modell.istAngehalten { angehalten(dokument) }
            }

            Section("Angaben") {
                zeile("Typ", Bezeichnung.dokumenttyp(dokument.docType))
                zeile("Seiten", dokument.totalPages.map(String.init) ?? "—")
                zeile("Versuche", String(dokument.attemptCount))
                zeile("Nächster Versuch", Zeitanzeige.text(dokument.nextRetryAt))
                zeile("Erstellt", Zeitanzeige.text(dokument.createdAt))
                zeile("Gestartet", Zeitanzeige.text(dokument.startedAt))
                zeile("Fertiggestellt", Zeitanzeige.text(dokument.finishedAt))
            }

            Section("Verlauf") {
                if modell.ereignisse.isEmpty {
                    Text(modell.geladen ? "Noch keine Ereignisse." : "Lädt …").foregroundStyle(.textLeise)
                }
                ForEach(modell.ereignisse) { ereignis in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack {
                            Text(Bezeichnung.ereignis(ereignis.eventType)).font(.subheadline.weight(.semibold))
                            Spacer()
                            Text(Zeitanzeige.text(ereignis.timestamp)).font(.caption).foregroundStyle(.textLeise)
                        }
                        if let text = ereignis.message, !text.isEmpty {
                            Text(text).font(.callout).foregroundStyle(.secondary)
                        }
                    }
                    .accessibilityElement(children: .combine)
                }
            }
        }
        .navigationTitle("Vorgang")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable { await modell.laden() }
        // Lädt beim Öffnen und erneut, wenn der Ereignisstrom eine Änderung an diesem Vorgang meldet.
        .task(id: historie.version(von: dokument.id)) { await modell.laden() }
        .alert(titel, isPresented: Binding(get: { zuBestaetigen != nil }, set: { if !$0 { zuBestaetigen = nil } }),
               presenting: zuBestaetigen) { entscheidung in
            switch entscheidung {
            case .freigeben:
                Button("Freigeben") { Task { await modell.entscheiden(.freigeben) } }
            case .verwerfen:
                Button("Verwerfen", role: .destructive) { Task { await modell.entscheiden(.verwerfen) } }
            }
            Button("Abbrechen", role: .cancel) {}
        } message: { entscheidung in
            Text(nachricht(entscheidung))
        }
    }

    private var titel: String {
        switch zuBestaetigen {
        case .freigeben: "Vorgang freigeben?"
        case .verwerfen: "Vorgang verwerfen?"
        case nil: ""
        }
    }

    private func nachricht(_ entscheidung: DetailModell.Entscheidung) -> String {
        switch entscheidung {
        case .freigeben: "Die Texterkennung läuft dann für alle Seiten. Dabei entstehen Kosten."
        case .verwerfen: "Der Vorgang wird nicht verarbeitet. Das Original kommt in den Fehlerordner."
        }
    }

    private func kopf(_ dokument: DokumentDTO) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(dokument.originalFilename).font(.headline)
            ZustandsMarke(dokument: dokument)
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("detail.kopf")
    }

    private func zeile(_ name: String, _ wert: String) -> some View {
        LabeledContent(name, value: wert)
    }

    /// `failed` hat mehrere Ursachen (ui-texte.md): bewusst verworfen, Versuche ausgeschöpft oder sonst.
    private func gescheitert(_ dokument: DokumentDTO) -> some View {
        let verworfen = modell.ereignisse.contains { $0.eventType == "discarded" }
        let ausgeschoepft = modell.versuchsGrenze.map { dokument.attemptCount >= $0 } ?? false
        return VStack(alignment: .leading, spacing: 6) {
            if verworfen {
                Text(dokument.errorMessage ?? "Verworfen.")
            } else {
                if ausgeschoepft {
                    Text("Endgültig fehlgeschlagen nach \(dokument.attemptCount) Versuchen.").bold()
                    Text("Das Original liegt im Fehlerordner. Für einen neuen Versuch die Datei wieder in den Eingangsordner legen oder erneut hochladen.")
                } else {
                    Text("Verarbeitung fehlgeschlagen.").bold()
                }
                if let grund = dokument.errorMessage { Text("Grund: \(grund)") }
            }
        }
        .font(.callout)
        .accessibilityIdentifier("detail.gescheitert")
    }

    private func angehalten(_ dokument: DokumentDTO) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Angehalten: **\(dokument.totalPages.map(String.init) ?? "?") Seiten** überschreiten die Grenze von **\(modell.seitenGrenze.map(String.init) ?? "?") Seiten**. Es wurde keine Texterkennung ausgeführt, es sind noch keine Kosten entstanden.")
                .font(.callout)
                .accessibilityIdentifier("detail.angehalten")
            Button("Freigeben und verarbeiten") { zuBestaetigen = .freigeben }
                .buttonStyle(.borderedProminent)
                .tint(.akzent)
                .disabled(modell.entscheidetGerade)
                .accessibilityIdentifier("detail.freigeben")
            Button("Verwerfen", role: .destructive) { zuBestaetigen = .verwerfen }
                .buttonStyle(.bordered)
                .disabled(modell.entscheidetGerade)
                .accessibilityIdentifier("detail.verwerfen")
        }
        .padding(12)
        .background(.violettFlaeche, in: RoundedRectangle(cornerRadius: 10))
    }
}
