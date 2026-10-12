import SwiftUI

/// Die Historie: Zähler je Zustand, Filter, Suche und die Liste der Vorgänge, neueste zuerst.
struct HistorieAnsicht: View {
    let modell: HistorieModell
    let client: APIClient

    @State private var suchtext = ""
    @State private var suchAufgabe: Task<Void, Never>?

    var body: some View {
        VStack(spacing: 0) {
            zaehlerLeiste
            filterLeiste
            inhalt
        }
        .searchable(text: $suchtext, prompt: "Dateiname suchen")
        .onChange(of: suchtext) { _, neu in
            suchAufgabe?.cancel()
            suchAufgabe = Task {
                try? await Task.sleep(for: .milliseconds(400))
                guard !Task.isCancelled else { return }
                await modell.sucheSetzen(neu)
            }
        }
        .onSubmit(of: .search) {
            suchAufgabe?.cancel()
            Task { await modell.sucheSetzen(suchtext) }
        }
    }

    // MARK: Zähler und Filter

    private var zaehlerLeiste: some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 3), spacing: 8) {
            ForEach(HistorieModell.zaehlerReihenfolge, id: \.self) { zustand in
                ZaehlerKachel(zustand: zustand, anzahl: modell.anzahl(zustand), gewaehlt: modell.statusFilter == zustand) {
                    Task { await modell.statusWaehlen(zustand) }
                }
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
    }

    private var filterLeiste: some View {
        HStack(spacing: 12) {
            Menu {
                Button { Task { await modell.statusWaehlen(modell.statusFilter) } } label: {
                    haken("Alle Zustände", modell.statusFilter == nil)
                }
                ForEach(DokumentZustand.allCases, id: \.self) { zustand in
                    Button { if modell.statusFilter != zustand { Task { await modell.statusWaehlen(zustand) } } } label: {
                        haken(zustand.bezeichnung, modell.statusFilter == zustand)
                    }
                }
            } label: {
                Label(modell.statusFilter?.bezeichnung ?? "Alle Zustände", systemImage: "line.3.horizontal.decrease")
            }
            .accessibilityIdentifier("historie.zustand")

            Menu {
                ForEach(Zeitraum.allCases, id: \.self) { zeitraum in
                    Button { Task { await modell.zeitraumWaehlen(zeitraum) } } label: {
                        haken(zeitraum.bezeichnung, modell.zeitraum == zeitraum)
                    }
                }
            } label: {
                Label(modell.zeitraum.bezeichnung, systemImage: "calendar")
            }
            .accessibilityIdentifier("historie.zeitraum")

            Spacer()
        }
        .font(.subheadline)
        .padding(.horizontal)
        .padding(.bottom, 8)
    }

    @ViewBuilder
    private func haken(_ text: String, _ gewaehlt: Bool) -> some View {
        if gewaehlt { Label(text, systemImage: "checkmark") } else { Text(text) }
    }

    // MARK: Liste

    @ViewBuilder
    private var inhalt: some View {
        if modell.dokumente.isEmpty {
            switch modell.ladezustand {
            case .unbekannt, .laedt:
                ProgressView("Lädt …")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .accessibilityIdentifier("historie.laedt")
            case .fehler(let text):
                ContentUnavailableView {
                    Label("Historie nicht geladen", systemImage: "exclamationmark.triangle")
                } description: {
                    Text(text)
                } actions: {
                    Button("Erneut versuchen") { Task { await modell.laden() } }
                        .accessibilityIdentifier("historie.erneut")
                }
            case .geladen:
                leer
            }
        } else {
            liste
        }
    }

    private var leer: some View {
        Group {
            if modell.filterAktiv {
                ContentUnavailableView {
                    Label("Nichts gefunden", systemImage: "line.3.horizontal.decrease.circle")
                } description: {
                    Text("Kein Vorgang passt zu den gewählten Filtern.")
                } actions: {
                    Button("Filter zurücksetzen") {
                        suchtext = ""
                        Task { await modell.filterZuruecksetzen() }
                    }
                    .accessibilityIdentifier("historie.filterZuruecksetzen")
                }
            } else {
                ContentUnavailableView("Noch keine Vorgänge", systemImage: "tray",
                                       description: Text("Sobald ein Beleg übergeben wird, erscheint er hier."))
            }
        }
    }

    private var liste: some View {
        List {
            if case .fehler(let text) = modell.ladezustand {
                Fehlerflaeche(text: text)
                    .listRowSeparator(.hidden)
                    .accessibilityIdentifier("historie.fehler")
            }
            ForEach(modell.dokumente) { dokument in
                NavigationLink {
                    DetailAnsicht(dokument: dokument, client: client, historie: modell)
                } label: {
                    ZeileAnsicht(dokument: dokument)
                }
                .accessibilityIdentifier("historie.zeile.\(dokument.id)")
            }
            if modell.weitereVerfuegbar {
                weitereZeile
            }
        }
        .listStyle(.plain)
        .refreshable { await modell.laden() }
        .accessibilityIdentifier("historie.liste")
    }

    private var weitereZeile: some View {
        VStack(spacing: 8) {
            if let fehler = modell.weitereFehler { Fehlerflaeche(text: fehler) }
            Button {
                Task { await modell.weitereLaden() }
            } label: {
                if modell.laedtWeitere { ProgressView() } else { Text("Weitere laden") }
            }
            .disabled(modell.laedtWeitere)
            .frame(maxWidth: .infinity)
            .accessibilityIdentifier("historie.weitere")
        }
    }
}

/// Kachel mit Zähler je Zustand; Tippen filtert danach. Farbe plus Text, nie Farbe allein.
private struct ZaehlerKachel: View {
    let zustand: DokumentZustand
    let anzahl: Int
    let gewaehlt: Bool
    let aktion: () -> Void

    var body: some View {
        Button(action: aktion) {
            VStack(alignment: .leading, spacing: 0) {
                Text("\(anzahl)").font(.title3.bold().monospacedDigit())
                Text(zustand.bezeichnung).font(.caption).lineLimit(1).minimumScaleFactor(0.8)
            }
            .foregroundStyle(zustand.farben.vordergrund.color)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(zustand.farben.flaeche.color, in: RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(.akzent, lineWidth: gewaehlt ? 2 : 0))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(zustand.bezeichnung): \(anzahl)")
        .accessibilityAddTraits(gewaehlt ? .isSelected : [])
        .accessibilityIdentifier("historie.zaehler.\(zustand.rawValue)")
    }
}

/// Zustandsbezeichnung als Marke: Farbe und Text zusammen.
struct ZustandsMarke: View {
    let dokument: DokumentDTO

    var body: some View {
        let farben = dokument.zustand?.farben
        Text(Bezeichnung.zustand(dokument))
            .font(.caption.weight(.semibold))
            .foregroundStyle(farben?.vordergrund.color ?? .secondary)
            .padding(.horizontal, 8)
            .padding(.vertical, 2)
            .background(farben?.flaeche.color ?? Color(.secondarySystemFill), in: Capsule())
    }
}

private struct ZeileAnsicht: View {
    let dokument: DokumentDTO

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(dokument.originalFilename)
                .font(.headline)
                .lineLimit(2)
            HStack(spacing: 8) {
                ZustandsMarke(dokument: dokument)
                Text(Zeitanzeige.text(dokument.createdAt))
                    .font(.caption)
                    .foregroundStyle(.textLeise)
            }
            if dokument.zustand == .processing, let gesamt = dokument.totalPages, gesamt > 0 {
                ProgressView(value: Double(min(dokument.processedPages, gesamt)), total: Double(gesamt))
                Text("Seite \(dokument.processedPages) von \(gesamt)")
                    .font(.caption)
                    .foregroundStyle(.textLeise)
            }
        }
        .padding(.vertical, 2)
        .accessibilityElement(children: .combine)
    }
}
