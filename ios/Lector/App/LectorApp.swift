import SwiftUI

@main
struct LectorApp: App {
    @State private var umgebung = AppAbhaengigkeiten()

    var body: some Scene {
        WindowGroup {
            WurzelAnsicht(umgebung: umgebung)
        }
    }
}

/// Schaltet zwischen Einrichtung, Anmeldung und Hauptansicht. Die Anmeldung erscheint auch nach
/// einem 401 mitten in der Nutzung, mit der bisherigen Serveradresse.
struct WurzelAnsicht: View {
    let umgebung: AppAbhaengigkeiten

    var body: some View {
        let sitzung = umgebung.sitzung
        Group {
            if sitzung.einrichtungNoetig {
                EinrichtungsAnsicht(sitzung: sitzung, konfiguration: umgebung.konfiguration, transport: umgebung.transport)
            } else if sitzung.anmeldungNoetig {
                AnmeldeAnsicht(modell: sitzung)
            } else {
                HauptAnsicht(sitzung: sitzung, client: umgebung.apiClient, ereignisQuelle: umgebung.ereignisQuelle)
            }
        }
        .task { await sitzung.beobachten() }
        .task {
            if umgebung.serverPruefungStartet { await sitzung.serverPruefen() }
        }
    }
}
