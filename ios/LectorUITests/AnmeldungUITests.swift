import XCTest

/// Einrichtung, Anmeldung und Serverwechsel gegen den Attrappen-Transport der App (Debug,
/// `UITestStart`): kein Netz, kein Keychain, keine App Group.
final class AnmeldungUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    @MainActor
    private func starten(_ zusatz: [String] = [], adresseGesetzt: Bool = true) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-UITEST_ATTRAPPE", "-UITEST_AUTH_MODUS", "paperless"]
            + (adresseGesetzt ? ["-UITEST_ADRESSE_GESETZT"] : []) + zusatz
        app.launch()
        return app
    }

    @MainActor
    private func tippen(_ feld: XCUIElement, _ text: String) {
        XCTAssertTrue(feld.waitForExistence(timeout: 10), "Feld fehlt: \(feld)")
        feld.tap()
        feld.typeText(text)
    }

    @MainActor
    private func anmelden(_ app: XCUIApplication, nutzer: String, passwort: String, code: String? = nil) {
        tippen(app.textFields["anmeldung.nutzername"], nutzer)
        let passwortFeld = app.secureTextFields["anmeldung.passwort"]
        tippen(passwortFeld, passwort)
        if let code { tippen(app.textFields["anmeldung.code"], code) }
        app.buttons["anmeldung.senden"].tap()
    }

    // MARK: Anmeldung

    @MainActor
    func testAnmeldungErfolg() {
        let app = starten()
        anmelden(app, nutzer: "anna", passwort: "richtig")
        XCTAssertTrue(app.buttons["historie.zaehler.done"].waitForExistence(timeout: 10), "Historie fehlt")
        XCTAssertFalse(app.buttons["anmeldung.senden"].exists)
    }

    @MainActor
    func testMfaErforderlichBehaeltEingaben() {
        let app = starten()
        anmelden(app, nutzer: "mfa-nutzer", passwort: "richtig")

        let meldung = app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'MFA-Code erforderlich'")).firstMatch
        XCTAssertTrue(meldung.waitForExistence(timeout: 10), "MFA-Hinweis fehlt")
        // Nutzername und Passwort bleiben eingetragen.
        XCTAssertEqual(app.textFields["anmeldung.nutzername"].value as? String, "mfa-nutzer")
        XCTAssertNotEqual(app.secureTextFields["anmeldung.passwort"].value as? String, "Passwort")

        tippen(app.textFields["anmeldung.code"], "123456")
        app.buttons["anmeldung.senden"].tap()
        XCTAssertTrue(app.buttons["historie.zaehler.done"].waitForExistence(timeout: 10), "Historie nach MFA fehlt")
    }

    @MainActor
    func testPaperlessNichtErreichbar() {
        let app = starten()
        anmelden(app, nutzer: "anna", passwort: "paperless-weg")
        let meldung = app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'Paperless ist nicht erreichbar'")).firstMatch
        XCTAssertTrue(meldung.waitForExistence(timeout: 10), "Meldung zu Paperless fehlt")
        XCTAssertFalse(app.buttons["historie.zaehler.done"].exists)
    }

    // MARK: Einrichtung

    @MainActor
    func testEinrichtungOhneLector() {
        let app = starten(adresseGesetzt: false)
        tippen(app.textFields["einrichtung.adresse"], "kein-lector.test")
        app.buttons["einrichtung.senden"].tap()
        let meldung = app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'kein Lector gefunden'")).firstMatch
        XCTAssertTrue(meldung.waitForExistence(timeout: 10), "Meldung „kein Lector“ fehlt")
        XCTAssertFalse(app.textFields["anmeldung.nutzername"].exists)
    }

    @MainActor
    func testEinrichtungFuehrtZurAnmeldung() {
        let app = starten(adresseGesetzt: false)
        tippen(app.textFields["einrichtung.adresse"], "lector.test")
        app.buttons["einrichtung.senden"].tap()
        XCTAssertTrue(app.textFields["anmeldung.nutzername"].waitForExistence(timeout: 10), "Anmeldung fehlt")
    }

    // MARK: Einstellungen

    @MainActor
    func testServerWechselnBisZurErneutenPruefung() {
        let app = starten(["-UITEST_ANGEMELDET"])
        app.buttons["haupt.einstellungen"].tap()
        XCTAssertTrue(app.buttons["einstellungen.serverWechseln"].waitForExistence(timeout: 10))
        app.buttons["einstellungen.serverWechseln"].tap()

        // Einrichtung mit der bisherigen Adresse vorausgefüllt.
        let feld = app.textFields["einrichtung.adresse"]
        XCTAssertTrue(feld.waitForExistence(timeout: 10), "Einrichtung fehlt")
        XCTAssertEqual(feld.value as? String, "https://lector.test")

        // Neue Adresse: erst ohne Lector abgewiesen, dann bestätigt; die alte Anmeldung ist beendet.
        feld.tap()
        feld.press(forDuration: 1.0)
        if app.menuItems["Alles auswählen"].waitForExistence(timeout: 2) { app.menuItems["Alles auswählen"].tap() }
        feld.typeText("kein-lector.test")
        app.buttons["einrichtung.senden"].tap()
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'kein Lector gefunden'")).firstMatch
            .waitForExistence(timeout: 10))
        feld.press(forDuration: 1.0)
        if app.menuItems["Alles auswählen"].waitForExistence(timeout: 2) { app.menuItems["Alles auswählen"].tap() }
        feld.typeText("zweiter.lector.test")
        app.buttons["einrichtung.senden"].tap()
        XCTAssertTrue(app.textFields["anmeldung.nutzername"].waitForExistence(timeout: 10),
                      "Nach bestätigter Adresse muss die Anmeldung kommen (alter Schlüssel beendet)")
    }

    @MainActor
    func testAbmelden() {
        let app = starten(["-UITEST_ANGEMELDET"])
        app.buttons["haupt.einstellungen"].tap()
        app.buttons["einstellungen.abmelden"].tap()
        XCTAssertTrue(app.textFields["anmeldung.nutzername"].waitForExistence(timeout: 10), "Anmeldung nach Abmelden fehlt")
    }
}
