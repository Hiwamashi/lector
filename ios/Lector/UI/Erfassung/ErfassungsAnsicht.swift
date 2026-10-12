import SwiftUI

/// Blatt nach Scan oder Fotoauswahl: zeigt Vorbereitung, Fortschritt und Ergebnis der Übergabe.
/// Beim Schließen wird der Arbeitsordner gelöscht; was nicht übergeben wurde, ist dann weg.
struct ErfassungsAnsicht: View {
    let modell: ErfassungsModell
    let schliessen: () -> Void

    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                Spacer()
                inhalt
                Spacer()
            }
            .padding()
            .frame(maxWidth: .infinity)
            .navigationTitle("Übergabe")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(modell.laeuft ? "Abbrechen" : "Fertig", action: schliessen)
                        .accessibilityIdentifier("erfassung.schliessen")
                }
            }
        }
        .interactiveDismissDisabled(modell.laeuft)
        .task { await modell.starten() }
        .onDisappear { modell.aufraeumen() }
    }

    @ViewBuilder
    private var inhalt: some View {
        switch modell.zustand {
        case .bereit, .vorbereiten:
            ProgressView("Beleg wird vorbereitet …")
                .accessibilityIdentifier("erfassung.vorbereiten")
        case .senden(let anteil):
            VStack(spacing: 12) {
                ProgressView(value: anteil) { Text("Wird an Lector gesendet …") }
                if let name = modell.dateiname { Text(name).font(.footnote).foregroundStyle(.textLeise) }
            }
            .accessibilityIdentifier("erfassung.senden")
        case .uebergeben:
            VStack(spacing: 10) {
                Image(systemName: "checkmark.circle.fill").font(.largeTitle).foregroundStyle(.gruen)
                Text("An Lector übergeben").font(.headline)
                Text("Die Verarbeitung läuft im Hintergrund. Den Stand siehst du in der Historie.")
                    .font(.callout).foregroundStyle(.textLeise).multilineTextAlignment(.center)
            }
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("erfassung.uebergeben")
        case .abgewiesen(let grund):
            Fehlerflaeche(text: "Nicht angenommen: \(grund)")
                .accessibilityIdentifier("erfassung.abgewiesen")
        case .fehlgeschlagen(let meldung):
            VStack(spacing: 14) {
                Fehlerflaeche(text: meldung)
                    .accessibilityIdentifier("erfassung.fehler")
                Button("Erneut senden") { Task { await modell.erneutSenden() } }
                    .buttonStyle(.borderedProminent)
                    .accessibilityIdentifier("erfassung.erneut")
                Text("Schließt du dieses Fenster, wird nichts später nachgeholt.")
                    .font(.footnote).foregroundStyle(.textLeise).multilineTextAlignment(.center)
            }
        }
    }
}
