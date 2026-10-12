import SwiftUI

/// Anmeldung im Modus `paperless`: Nutzername, Passwort und optionaler MFA-Code. Bei „MFA-Code
/// erforderlich“ bleiben die Eingaben stehen, und der Fokus springt in das Codefeld.
struct AnmeldeAnsicht: View {
    let modell: SitzungsModell

    @State private var nutzername = ""
    @State private var passwort = ""
    @State private var code = ""
    @FocusState private var fokus: Feld?

    private enum Feld { case nutzername, passwort, code }

    private var kannSenden: Bool {
        SitzungsModell.eingabeGueltig(nutzername: nutzername, passwort: passwort) && !modell.laeuft
    }

    var body: some View {
        ScrollViewReader { leser in
            ScrollView {
                formular
            }
            .scrollDismissesKeyboard(.interactively)
            // Ein Fehler ist sonst nur sichtbar, wenn er zufällig im Bild liegt, und VoiceOver hört nichts.
            .onChange(of: modell.fehlermeldung, initial: true) { _, neu in
                guard let neu else { return }
                AccessibilityNotification.Announcement(neu).post()
                Task { @MainActor in leser.scrollTo("meldung", anchor: .center) }
            }
            .onChange(of: modell.mfaErforderlich) { _, neu in
                if neu { fokus = .code }
            }
        }
    }

    private var formular: some View {
        VStack(alignment: .leading, spacing: 24) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Anmelden").font(.largeTitle.bold())
                Text("Melde dich mit deinem Paperless-Konto an.").foregroundStyle(.secondary)
                if let adresse = modell.serverAdresse {
                    Text(adresse.absoluteString).font(.footnote).foregroundStyle(.secondary)
                        .accessibilityIdentifier("anmeldung.server")
                }
            }

            VStack(alignment: .leading, spacing: 16) {
                feld("Nutzername") {
                    TextField("Nutzername", text: $nutzername)
                        .textContentType(.username)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .submitLabel(.next)
                        .focused($fokus, equals: .nutzername)
                        .onSubmit { fokus = .passwort }
                        .accessibilityIdentifier("anmeldung.nutzername")
                }
                feld("Passwort") {
                    SecureField("Passwort", text: $passwort)
                        .textContentType(.password)
                        .submitLabel(.next)
                        .focused($fokus, equals: .passwort)
                        .onSubmit { fokus = .code }
                        .accessibilityIdentifier("anmeldung.passwort")
                }
                feld("MFA-Code (falls aktiviert)", hervorgehoben: modell.mfaErforderlich) {
                    TextField("MFA-Code", text: $code)
                        .textContentType(.oneTimeCode)
                        .keyboardType(.numberPad)
                        .submitLabel(.go)
                        .focused($fokus, equals: .code)
                        .onSubmit(senden)
                        .accessibilityIdentifier("anmeldung.code")
                }
            }

            if let meldung = modell.fehlermeldung {
                Fehlerflaeche(text: meldung, art: modell.mfaErforderlich ? .hinweis : .fehler)
                    .id("meldung")
                    .accessibilityIdentifier("anmeldung.fehler")
            }

            Button(action: senden) {
                Group {
                    if modell.laeuft {
                        ProgressView().tint(.akzentAuf).accessibilityLabel("Anmeldung läuft")
                    } else {
                        Text("Anmelden")
                    }
                }
                .font(.headline)
                .foregroundStyle(.akzentAuf)
                .frame(maxWidth: .infinity, minHeight: 48)
                .background(.akzent, in: RoundedRectangle(cornerRadius: 10))
                .opacity(kannSenden || modell.laeuft ? 1 : 0.5)
            }
            .disabled(!kannSenden)
            .accessibilityIdentifier("anmeldung.senden")

            Button("Anderen Server einrichten") {
                Task { await modell.serverWechseln() }
            }
            .font(.subheadline)
            .frame(maxWidth: .infinity)
            .accessibilityIdentifier("anmeldung.serverWechseln")
        }
        .padding(24)
        .frame(maxWidth: 480)
        .frame(maxWidth: .infinity)
    }

    private func feld(_ titel: String, hervorgehoben: Bool = false, @ViewBuilder inhalt: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            // Der Name gehört dem Feld selbst; das sichtbare Label daneben wäre doppelt vorgelesen.
            Text(titel).font(.footnote).foregroundStyle(.secondary).accessibilityHidden(true)
            inhalt()
                .accessibilityLabel(titel)
                .padding(.horizontal, 12)
                .frame(minHeight: 48)
                .background(.fill.tertiary, in: RoundedRectangle(cornerRadius: 10))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.akzent, lineWidth: hervorgehoben ? 2 : 0))
        }
    }

    private func senden() {
        guard kannSenden else { return }
        fokus = nil
        Task { await modell.anmelden(nutzername: nutzername, passwort: passwort, code: code) }
    }
}
