import PhotosUI
import SwiftUI

/// Rahmen der angemeldeten App: Navigation, Einstellungen und die Historie. Die Live-Aktualisierung
/// läuft nur, solange die App im Vordergrund ist (D11).
struct HauptAnsicht: View {
    /// Inhalt der Vollbild-Ansicht; `testscan` ersetzt in Debug die Kamera (UI-Tests).
    private enum Scannerart: Identifiable {
        case kamera
        #if DEBUG
        case testscan
        #endif

        var id: Self { self }
    }

    let sitzung: SitzungsModell
    let client: APIClient
    @State private var historie: HistorieModell
    @State private var einstellungenOffen = false
    @State private var erfassung: ErfassungsModell?
    /// Das Modell des geöffneten Blatts; `erfassung` ist beim Schließen schon wieder `nil`.
    @State private var offeneErfassung: ErfassungsModell?
    /// Die Bilder des beendeten Scans; übergeben wird erst, wenn der Scanner ganz geschlossen ist.
    @State private var ausstehenderScan: [UIImage]?
    @State private var scannerArt: Scannerart?
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
                            Button("Beleg scannen", systemImage: "doc.viewfinder") { scannerArt = .kamera }
                                .accessibilityIdentifier("haupt.scannen")
                        }
                        Button("Fotos auswählen", systemImage: "photo.on.rectangle") { fotosOffen = true }
                            .accessibilityIdentifier("haupt.fotos")
                        #if DEBUG
                        if UITestStart.testbildEingespeist {
                            Button("Testbild übergeben") { testbildUebergeben() }
                                .accessibilityIdentifier("haupt.testbild")
                        }
                        if UITestStart.testscanEingespeist {
                            Button("Testscan übergeben") { scannerArt = .testscan }
                                .accessibilityIdentifier("haupt.testscan")
                        }
                        #endif
                    }
                    .accessibilityIdentifier("haupt.hinzufuegen")
                }
            }
            .sheet(isPresented: $einstellungenOffen) {
                EinstellungenAnsicht(sitzung: sitzung)
            }
            .fullScreenCover(item: $scannerArt, onDismiss: scannerGeschlossen) { art in
                scannerInhalt(art)
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
        .task {
            // Reste früherer Läufe (Absturz, abgelaufene Sitzung mit offenem Blatt) wegräumen.
            ErfassungsModell.verwaisteAufraeumen(ausser: offeneErfassung?.arbeitsordner)
            if szene == .active { historie.vordergrund() }
        }
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

    @ViewBuilder
    private func scannerInhalt(_ art: Scannerart) -> some View {
        switch art {
        case .kamera:
            DokumentScanner(fertig: scanBeendet, abgebrochen: { scanBeendet(nil) })
                .ignoresSafeArea()
        #if DEBUG
        case .testscan:
            TestscanAnsicht(fertig: scanBeendet, abgebrochen: { scanBeendet(nil) })
        #endif
        }
    }

    /// Gemeinsamer Ausgang von Scanner und Testscan: merkt sich die Bilder und schließt die
    /// Vollbild-Ansicht; `nil` oder keine Bilder heißt abgebrochen. Das Blatt öffnet erst
    /// `scannerGeschlossen`, damit sich Schließen und Öffnen nicht überlagern.
    private func scanBeendet(_ bilder: [UIImage]?) {
        ausstehenderScan = bilder?.isEmpty == false ? bilder : nil
        scannerArt = nil
    }

    /// Die Vollbild-Ansicht ist vollständig weg: jetzt die Übergabe starten, falls ein Scan vorliegt.
    private func scannerGeschlossen() {
        guard let bilder = ausstehenderScan else { return }
        ausstehenderScan = nil
        uebergeben { _ in bilder.map { .bild($0) } }
    }

    private func uebergeben(_ seiten: @escaping @MainActor (URL) async throws -> [PDFSeite]) {
        // Ein noch vorgemerktes Modell würde sonst überschrieben und sein Ordner bliebe liegen.
        offeneErfassung?.aufraeumen()
        let modell = ErfassungsModell(client: client, seiten: seiten)
        offeneErfassung = modell
        erfassung = modell
    }

    /// Das Blatt ist geschlossen: erst jetzt wird der Arbeitsordner gelöscht, nicht schon beim bloßen
    /// Verschwinden der Ansicht. Wird dasselbe Modell erneut präsentiert, bleibt es unberührt.
    /// Danach sofort nachladen; der Ereignisstrom meldet den Vorgang sonst erst mit Verzögerung.
    private func nachErfassung() {
        if let modell = offeneErfassung, erfassung !== modell {
            modell.aufraeumen()
            offeneErfassung = nil
        }
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

    #if DEBUG
    /// Ersatz für die Kamera im Simulator: Vollbild-Ansicht mit „Speichern“ und „Abbrechen“.
    private struct TestscanAnsicht: View {
        let fertig: ([UIImage]) -> Void
        let abgebrochen: () -> Void

        var body: some View {
            VStack(spacing: 20) {
                Text("Testscan")
                Button("Speichern") { fertig(UITestStart.testbilder()) }
                    .buttonStyle(.borderedProminent)
                    .accessibilityIdentifier("testscan.speichern")
                Button("Abbrechen", action: abgebrochen)
                    .accessibilityIdentifier("testscan.abbrechen")
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color(.systemBackground))
        }
    }
    #endif
}
