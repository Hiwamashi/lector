import Foundation

/// Wo die Sitzung steht. Im Modus `paperless` entscheidet das darüber, ob die App die Anmeldung zeigt.
enum Sitzungszustand: Equatable, Sendable {
    /// Ein Zugangsschlüssel liegt im Schlüsselspeicher.
    case angemeldet
    /// Kein Schlüssel: nie angemeldet, abgemeldet oder vom Dienst abgelehnt (401).
    case anmeldungNoetig
}

/// Die vier Ablehnungsgründe der Anmeldung (D4) plus die Fälle, die der Client selbst kennt.
enum AnmeldeFehler: Error, Equatable {
    case ungueltigeAnmeldedaten
    case mfaErforderlich
    case paperlessNichtErreichbar
    case gebremst
    case keinNetz
    case keineServeradresse
    case unerwartet(status: Int)
}

/// Hält die Sitzung: den Zugangsschlüssel im `TokenStore` und den Zustand. Es gibt keinen
/// Refresh-Ablauf; der Schlüssel läuft nicht ab, der Dienst entscheidet allein (D2).
actor AuthSession {
    private let konfiguration: ServerKonfiguration
    private let transport: any Transport
    private let tokenStore: any TokenStore

    private(set) var zustand: Sitzungszustand {
        didSet {
            guard zustand != oldValue else { return }
            for beobachter in beobachter.values { beobachter.yield(zustand) }
        }
    }
    private var beobachter: [UUID: AsyncStream<Sitzungszustand>.Continuation] = [:]

    init(konfiguration: ServerKonfiguration, transport: any Transport, tokenStore: any TokenStore) {
        self.konfiguration = konfiguration
        self.transport = transport
        self.tokenStore = tokenStore
        self.zustand = Self.anfangszustand(tokenStore: tokenStore)
    }

    /// Ohne Actor-Hop berechenbar, damit die UI beim Start nicht erst einen Frame den falschen Bildschirm zeigt.
    nonisolated static func anfangszustand(tokenStore: any TokenStore) -> Sitzungszustand {
        tokenStore.lesen() != nil ? .angemeldet : .anmeldungNoetig
    }

    /// Aktueller Zustand sofort, danach jede Änderung.
    func zustandsfolge() -> AsyncStream<Sitzungszustand> {
        let (strom, fortsetzung) = AsyncStream.makeStream(of: Sitzungszustand.self, bufferingPolicy: .bufferingNewest(1))
        let id = UUID()
        beobachter[id] = fortsetzung
        fortsetzung.onTermination = { [weak self] _ in
            Task { await self?.beobachterEntfernen(id) }
        }
        fortsetzung.yield(zustand)
        return strom
    }

    private func beobachterEntfernen(_ id: UUID) {
        beobachter[id] = nil
    }

    /// Der Zugangsschlüssel, sofern vorhanden.
    func schluessel() -> String? {
        tokenStore.lesen()
    }

    // MARK: - Anmelden

    /// Das Passwort und der MFA-Code werden nur gesendet, nie gespeichert.
    func anmelden(nutzername: String, passwort: String, code: String?) async throws {
        guard let basis = konfiguration.adresse else { throw AnmeldeFehler.keineServeradresse }
        let bereinigt = code?.trimmingCharacters(in: .whitespacesAndNewlines)
        let request = try Anfrage.bauen(
            basis: basis, methode: "POST", pfad: "/api/v1/login",
            rumpf: LoginAnfrage(username: nutzername, password: passwort, code: bereinigt?.isEmpty == false ? bereinigt : nil),
            zeitlimit: 20)

        let daten: Data, antwort: HTTPURLResponse
        do {
            (daten, antwort) = try await Anfrage.uebertragen(request, ueber: transport)
        } catch APIFehler.keinNetz {
            throw AnmeldeFehler.keinNetz
        }

        if antwort.statusCode == 200 {
            guard let login = try? JSONKodierung.decoder().decode(LoginAntwort.self, from: daten) else {
                throw APIFehler.ungueltigeAntwort
            }
            try tokenStore.speichern(login.token)
            zustand = .angemeldet
            return
        }
        guard case .server(let status, let code, _) = Anfrage.fehler(status: antwort.statusCode, daten: daten) else {
            throw AnmeldeFehler.unerwartet(status: antwort.statusCode)
        }
        switch code {
        case .ungueltigeAnmeldedaten: throw AnmeldeFehler.ungueltigeAnmeldedaten
        case .mfaErforderlich: throw AnmeldeFehler.mfaErforderlich
        case .paperlessNichtErreichbar: throw AnmeldeFehler.paperlessNichtErreichbar
        case .gebremst: throw AnmeldeFehler.gebremst
        default: throw AnmeldeFehler.unerwartet(status: status)
        }
    }

    // MARK: - Ende der Sitzung

    /// Der Dienst hat mit 401 geantwortet: Schlüssel verwerfen, Zustand „Anmeldung nötig“. Die
    /// Serveradresse bleibt. Wurde inzwischen ein neuer Schlüssel gespeichert (Anmeldung während
    /// einer laufenden Anfrage), bleibt er erhalten: Abgelehnt wurde nur der alte.
    func sitzungAbgelaufen(abgelehnt: String?) {
        if let aktuell = tokenStore.lesen(), aktuell != abgelehnt { return }
        tokenStore.loeschen()
        zustand = .anmeldungNoetig
    }

    /// Meldet beim Dienst ab, soweit erreichbar, und entfernt den Schlüssel in jedem Fall.
    func abmelden() async {
        if let schluessel = tokenStore.lesen(), let basis = konfiguration.adresse,
           let request = try? Anfrage.bauen(basis: basis, methode: "POST", pfad: "/api/v1/logout", bearer: schluessel, zeitlimit: 8) {
            // Kurzes Zeitlimit: Offline soll das Abmelden nicht hängen, und das Ergebnis ist egal.
            _ = try? await Anfrage.uebertragen(request, ueber: transport)
        }
        tokenStore.loeschen()
        zustand = .anmeldungNoetig
    }
}
