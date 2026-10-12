import SwiftUI

/// Einstellungen: eingerichteter Server, Abmelden und Server wechseln.
struct EinstellungenAnsicht: View {
    let sitzung: SitzungsModell
    @Environment(\.dismiss) private var schliessen

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    LabeledContent("Adresse", value: sitzung.serverAdresse?.absoluteString ?? "–")
                        .accessibilityIdentifier("einstellungen.adresse")
                    Button("Server wechseln") {
                        Task {
                            await sitzung.serverWechseln()
                            schliessen()
                        }
                    }
                    .accessibilityIdentifier("einstellungen.serverWechseln")
                } header: {
                    Text("Server")
                } footer: {
                    Text("Beim Wechsel wirst du auf diesem Gerät vom bisherigen Server abgemeldet.")
                }

                if sitzung.kannAbmelden {
                    Section("Konto") {
                        Button("Abmelden", role: .destructive) {
                            Task {
                                await sitzung.abmelden()
                                schliessen()
                            }
                        }
                        .accessibilityIdentifier("einstellungen.abmelden")
                    }
                }
            }
            .navigationTitle("Einstellungen")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Fertig") { schliessen() }
                        .accessibilityIdentifier("einstellungen.fertig")
                }
            }
        }
    }
}
