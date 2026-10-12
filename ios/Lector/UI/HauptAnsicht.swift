import PhotosUI
import SwiftUI

/// Rahmen der angemeldeten App: Navigation, Einstellungen und die Historie. Die Live-Aktualisierung
/// läuft nur, solange die App im Vordergrund ist (D11).
struct HauptAnsicht: View {
    let sitzung: SitzungsModell
    let client: APIClient
    @State private var historie: HistorieModell
    @State private var einstellungenOffen = false
    @State private var erfassung: ErfassungsModell?
    @State private var scannerOffen = false
    @State private var fotosOffen = false
    @State private var fotoAuswahl: [PhotosPickerItem] = []
    @Environment(\.scenePhase) private var szene

    init(sitzung: SitzungsModell, client: APIClient, ereignisQuelle: any EreignisQuelle) {
        self.sitzung = sitzung
        self.client = client
        _historie = State(initialValue: HistorieModell(client: client, strom: EreignisStrom(client: client, quelle: ereignisQuelle)))
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 8) {
                if let hinweis = sitzung.serverHinweis {
                    Fehlerflaeche(text: hinweis)
                        .padding(.horizontal)
                        .accessibilityIdentifier("haupt.hinweis")
                }
                HistorieAnsicht(modell: historie, client: client)
            }
            .navigationTitle("Lector")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Einstellungen", systemImage: "gearshape") { einstellungenOffen = true }
                        .accessibilityIdentifier("haupt.einstellungen")
                }
                ToolbarItem(placement: .topBarLeading) {
                    Menu("Beleg übergeben", systemImage: "plus") {
                        if DokumentScanner.unterstuetzt {
                            Button("Beleg scannen", systemImage: "doc.viewfinder") { scannerOffen = true }
                                .accessibilityIdentifier("haupt.scannen")
                        }
                        Button("Fotos auswählen", systemImage: "photo.on.rectangle") { fotosOffen = true }
                            .accessibilityIdentifier("haupt.fotos")
                        #if DEBUG
                        if UITestStart.testbildEingespeist {
                            Button("Testbild übergeben") { testbildUebergeben() }
                                .accessibilityIdentifier("haupt.testbild")
                        }
                        #endif
                    }
                    .accessibilityIdentifier("haupt.hinzufuegen")
                }
            }
            .sheet(isPresented: $einstellungenOffen) {
                EinstellungenAnsicht(sitzung: sitzung)
            }
            .fullScreenCover(isPresented: $scannerOffen) {
                DokumentScanner(
                    fertig: { bilder in
                        scannerOffen = false
                        if !bilder.isEmpty { uebergeben { _ in bilder.map { .bild($0) } } }
                    },
                    abgebrochen: { scannerOffen = false })
                .ignoresSafeArea()
            }
            .photosPicker(isPresented: $fotosOffen, selection: $fotoAuswahl, matching: .images)
            .onChange(of: fotoAuswahl) { _, auswahl in
                guard !auswahl.isEmpty else { return }
                fotoAuswahl = []
                uebergeben { ordner in try await Self.fotosAblegen(auswahl, in: ordner) }
            }
            .sheet(item: $erfassung, onDismiss: nachErfassung) { modell in
                ErfassungsAnsicht(modell: modell) { erfassung = nil }
            }
        }
        .accessibilityIdentifier("haupt.historie")
        .task { if szene == .active { historie.vordergrund() } }
        .onChange(of: szene) { _, neu in
            switch neu {
            case .active: historie.vordergrund()
            case .background: historie.hintergrund()
            default: break
            }
        }
        .onDisappear { historie.hintergrund() }
    }

    // MARK: Erfassung

    private func uebergeben(_ seiten: @escaping @MainActor (URL) async throws -> [PDFSeite]) {
        erfassung = ErfassungsModell(client: client, seiten: seiten)
    }

    /// Nach dem Schließen sofort nachladen; der Ereignisstrom meldet den Vorgang sonst erst mit Verzögerung.
    private func nachErfassung() {
        Task { await historie.laden(still: true) }
    }

    /// Lädt die gewählten Fotos nacheinander und legt jedes als Datei ab (nicht alle im Speicher).
    private static func fotosAblegen(_ auswahl: [PhotosPickerItem], in ordner: URL) async throws -> [PDFSeite] {
        var seiten: [PDFSeite] = []
        for element in auswahl {
            try Task.checkCancellation()
            guard let daten = try await element.loadTransferable(type: Data.self) else { throw PDFFehler.bildNichtLesbar(seite: seiten.count) }
            let url = ordner.appendingPathComponent("foto-\(seiten.count)")
            try daten.write(to: url)
            seiten.append(.datei(url))
        }
        return seiten
    }

    #if DEBUG
    /// UI-Tests: umgeht Kamera und Fotoauswahl und übergibt drei erzeugte Bilder.
    private func testbildUebergeben() {
        uebergeben { _ in UITestStart.testbilder().map { .bild($0) } }
    }
    #endif
}
