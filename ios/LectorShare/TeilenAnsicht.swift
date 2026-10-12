import SwiftUI

/// Oberfläche der Share Extension: je Datei Name, Fortschritt und Ergebnis; bei fehlender
/// Einrichtung oder Anmeldung nur der Hinweis.
struct TeilenAnsicht: View {
    let modell: TeilenModell
    let schliessen: () -> Void

    var body: some View {
        NavigationStack {
            Group {
                switch modell.voraussetzung {
                case .erfuellt: liste
                case .nichtEingerichtet, .nichtAngemeldet: hinweis
                }
            }
            .navigationTitle("An Lector senden")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(modell.abgeschlossen ? "Fertig" : "Schließen", action: schliessen)
                }
            }
        }
        .task { await modell.starten() }
    }

    private var hinweis: some View {
        ContentUnavailableView {
            Label("Nicht angemeldet", systemImage: "person.crop.circle.badge.exclamationmark")
        } description: {
            Text("Bitte zuerst in der Lector-App anmelden.")
        }
    }

    private var liste: some View {
        List {
            ForEach(modell.eintraege) { eintrag in
                EintragZeile(eintrag: eintrag)
            }
            if modell.anmeldungAbgelaufen {
                Text("Die Anmeldung ist abgelaufen. Bitte in der Lector-App neu anmelden.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            if modell.kannErneutSenden {
                Button("Erneut senden") { Task { await modell.erneutSenden() } }
            }
        }
    }
}

private struct EintragZeile: View {
    let eintrag: TeilenModell.Eintrag

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                Text(eintrag.dateiname).lineLimit(2)
                Spacer(minLength: 8)
                symbol
            }
            switch eintrag.status {
            case .senden(let anteil):
                ProgressView(value: anteil)
            case .vorbereiten:
                ProgressView().controlSize(.small)
            default:
                EmptyView()
            }
            if let text {
                Text(text).font(.footnote).foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder private var symbol: some View {
        switch eintrag.status {
        case .angenommen:
            Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
        case .abgewiesen, .fehlgeschlagen:
            Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.red)
        default:
            EmptyView()
        }
    }

    private var text: String? {
        switch eintrag.status {
        case .wartet: "Wartet"
        case .vorbereiten: "Wird vorbereitet"
        case .senden: nil
        case .angenommen: "Übergeben"
        case .abgewiesen(let grund), .fehlgeschlagen(let grund): grund
        }
    }
}
