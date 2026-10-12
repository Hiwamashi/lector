import SwiftUI

/// Erster Bildschirm der App: Adresse des Lector-Dienstes eingeben und prüfen lassen. Auch der
/// Weg für „Server wechseln“, dann mit der bisherigen Adresse vorausgefüllt und mit „Abbrechen“.
struct EinrichtungsAnsicht: View {
    let sitzung: SitzungsModell
    @State private var modell: EinrichtungsModell
    @FocusState private var fokus: Bool

    init(sitzung: SitzungsModell, konfiguration: ServerKonfiguration, transport: any Transport) {
        self.sitzung = sitzung
        _modell = State(initialValue: EinrichtungsModell(konfiguration: konfiguration, transport: transport))
    }

    private var kannSenden: Bool {
        !modell.eingabe.trimmingCharacters(in: .whitespaces).isEmpty && !modell.laeuft
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Lector einrichten").font(.largeTitle.bold())
                        Text("Gib die Adresse deines Lector-Dienstes ein.").foregroundStyle(.secondary)
                    }

                    VStack(alignment: .leading, spacing: 6) {
                        Text("Adresse").font(.footnote).foregroundStyle(.secondary).accessibilityHidden(true)
                        TextField("lector.example.de", text: $modell.eingabe)
                            .keyboardType(.URL)
                            .textContentType(.URL)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .submitLabel(.go)
                            .focused($fokus)
                            .onSubmit(senden)
                            .padding(.horizontal, 12)
                            .frame(minHeight: 48)
                            .background(.fill.tertiary, in: RoundedRectangle(cornerRadius: 10))
                            .accessibilityLabel("Adresse")
                            .accessibilityIdentifier("einrichtung.adresse")
                    }

                    if let meldung = modell.fehlermeldung {
                        Fehlerflaeche(text: meldung)
                            .accessibilityIdentifier("einrichtung.fehler")
                    }

                    Button(action: senden) {
                        Group {
                            if modell.laeuft {
                                ProgressView().tint(.akzentAuf).accessibilityLabel("Adresse wird geprüft")
                            } else {
                                Text("Prüfen und fortfahren")
                            }
                        }
                        .font(.headline)
                        .foregroundStyle(.akzentAuf)
                        .frame(maxWidth: .infinity, minHeight: 48)
                        .background(.akzent, in: RoundedRectangle(cornerRadius: 10))
                        .opacity(kannSenden || modell.laeuft ? 1 : 0.5)
                    }
                    .disabled(!kannSenden)
                    .accessibilityIdentifier("einrichtung.senden")
                }
                .padding(24)
                .frame(maxWidth: 480)
                .frame(maxWidth: .infinity)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: modell.fehlermeldung, initial: true) { _, neu in
                guard let neu else { return }
                AccessibilityNotification.Announcement(neu).post()
            }
            .toolbar {
                if sitzung.serverAdresse != nil {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Abbrechen") { sitzung.einrichtungAbbrechen() }
                            .accessibilityIdentifier("einrichtung.abbrechen")
                    }
                }
            }
        }
    }

    private func senden() {
        guard kannSenden else { return }
        fokus = false
        Task {
            if await modell.pruefenUndSpeichern() { sitzung.einrichtungAbgeschlossen() }
        }
    }
}
