import XCTest

/// Historie und Detail gegen den Attrappen-Dienst der App (Debug, `UITestDienst`): Bestand 7 bis 1,
/// siehe dort. Kein Netz, kein Keychain.
final class HistorieUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    @MainActor
    private func starten(_ zusatz: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-UITEST_ATTRAPPE", "-UITEST_ADRESSE_GESETZT", "-UITEST_ANGEMELDET",
                               "-UITEST_AUTH_MODUS", "paperless"] + zusatz
        app.launch()
        return app
    }

    @MainActor
    private func zeile(_ app: XCUIApplication, _ id: Int) -> XCUIElement {
        app.buttons["historie.zeile.\(id)"]
    }

    @MainActor
    private func oeffnen(_ app: XCUIApplication, _ id: Int) {
        let eintrag = zeile(app, id)
        XCTAssertTrue(eintrag.waitForExistence(timeout: 10), "Zeile \(id) fehlt")
        eintrag.tap()
    }

    // MARK: 5.1 Historie

    @MainActor
    func testHistorieZeigtZaehlerUndVorgaenge() {
        let app = starten()
        XCTAssertTrue(zeile(app, 7).waitForExistence(timeout: 10), "Neuester Vorgang fehlt")
        // Zähler: je Zustand der ganze Bestand (2 angehalten, je 1 sonst).
        XCTAssertEqual(app.buttons["historie.zaehler.blocked"].label, "Angehalten: 2")
        XCTAssertEqual(app.buttons["historie.zaehler.done"].label, "Fertig: 1")
        XCTAssertEqual(app.buttons["historie.zaehler.processing"].label, "In Arbeit: 1")
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'Kassenbon-Edeka.pdf'")).firstMatch.exists)
        // Seitenfortschritt bei laufender Verarbeitung.
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'Seite 2 von 5'")).firstMatch.exists)
    }

    @MainActor
    func testFilterNachZustandLaesstZaehlerStehen() {
        let app = starten()
        XCTAssertTrue(zeile(app, 7).waitForExistence(timeout: 10))
        app.buttons["historie.zaehler.failed"].tap()
        XCTAssertTrue(zeile(app, 4).waitForExistence(timeout: 10))
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: zeile(app, 7))
        waitForExpectations(timeout: 10)
        XCTAssertFalse(zeile(app, 2).exists)
        XCTAssertEqual(app.buttons["historie.zaehler.done"].label, "Fertig: 1", "Zähler zeigen weiter den ganzen Bestand")
    }

    @MainActor
    func testFilterNachZeitraum() {
        let app = starten()
        XCTAssertTrue(zeile(app, 1).waitForExistence(timeout: 10), "Der alte Vorgang ist ohne Zeitraumfilter sichtbar")
        app.buttons["historie.zeitraum"].tap()
        app.buttons["Letzte 24 h"].tap()
        let verschwunden = NSPredicate(format: "exists == false")
        expectation(for: verschwunden, evaluatedWith: zeile(app, 1))
        waitForExpectations(timeout: 10)
        XCTAssertTrue(zeile(app, 7).exists)
    }

    @MainActor
    func testSucheFiltertDieListe() {
        let app = starten()
        XCTAssertTrue(zeile(app, 7).waitForExistence(timeout: 10))
        let suche = app.searchFields.firstMatch
        XCTAssertTrue(suche.waitForExistence(timeout: 5))
        suche.tap()
        suche.typeText("Telekom\n")
        XCTAssertTrue(zeile(app, 1).waitForExistence(timeout: 10))
        let verschwunden = NSPredicate(format: "exists == false")
        expectation(for: verschwunden, evaluatedWith: zeile(app, 7))
        waitForExpectations(timeout: 10)
    }

    @MainActor
    func testSucheOhneTrefferZeigtLeerzustand() {
        let app = starten()
        XCTAssertTrue(zeile(app, 7).waitForExistence(timeout: 10))
        let suche = app.searchFields.firstMatch
        XCTAssertTrue(suche.waitForExistence(timeout: 5))
        suche.tap()
        suche.typeText("gibt-es-nicht\n")
        XCTAssertTrue(app.buttons["historie.filterZuruecksetzen"].waitForExistence(timeout: 10), "Leerzustand fehlt")
        app.buttons["historie.filterZuruecksetzen"].tap()
        XCTAssertTrue(zeile(app, 7).waitForExistence(timeout: 10))
    }

    // MARK: 5.2 Live

    @MainActor
    func testLiveAktualisierungOhneManuellesLaden() {
        let app = starten(["-UITEST_LIVE"])
        XCTAssertTrue(zeile(app, 2).waitForExistence(timeout: 10))
        XCTAssertEqual(app.buttons["historie.zaehler.processing"].label, "In Arbeit: 1")
        // Nach 5 s meldet der Strom Vorgang 2 als fertig, nach 7 s kommt Vorgang 8 neu dazu.
        expectation(for: NSPredicate(format: "label == %@", "In Arbeit: 0"),
                    evaluatedWith: app.buttons["historie.zaehler.processing"])
        waitForExpectations(timeout: 25)
        XCTAssertTrue(zeile(app, 8).waitForExistence(timeout: 25), "Neuer Vorgang muss oben erscheinen")
        XCTAssertEqual(app.buttons["historie.zaehler.pending"].label, "Wartet: 2")
    }

    // MARK: 5.3 Detail

    @MainActor
    func testDetailZeigtVerlaufUndAngaben() {
        let app = starten()
        oeffnen(app, 2)
        XCTAssertTrue(app.staticTexts["Verlauf"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Texterkennung"].waitForExistence(timeout: 5), "Verlaufseintrag fehlt")
        XCTAssertFalse(app.buttons["detail.freigeben"].exists, "Nur angehaltene Vorgänge bieten Entscheidungen")
    }

    @MainActor
    func testFreigabeNurNachBestaetigung() {
        let app = starten()
        oeffnen(app, 3)
        let hinweis = app.staticTexts["detail.angehalten"]
        XCTAssertTrue(hinweis.waitForExistence(timeout: 10))
        XCTAssertTrue(hinweis.label.contains("120 Seiten"))
        XCTAssertTrue(hinweis.label.contains("100 Seiten"))

        // Abbruch im Dialog: nichts geschieht, der Vorgang bleibt angehalten.
        app.buttons["detail.freigeben"].tap()
        let dialog = app.alerts["Vorgang freigeben?"]
        XCTAssertTrue(dialog.waitForExistence(timeout: 5))
        dialog.buttons["Abbrechen"].tap()
        XCTAssertFalse(dialog.exists)
        XCTAssertTrue(app.buttons["detail.freigeben"].exists)

        // Bestätigen: Der Vorgang ist danach nicht mehr angehalten (wartet auf die Verarbeitung).
        app.buttons["detail.freigeben"].tap()
        XCTAssertTrue(dialog.waitForExistence(timeout: 5))
        dialog.buttons["Freigeben"].tap()
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: app.buttons["detail.freigeben"])
        waitForExpectations(timeout: 10)
        XCTAssertTrue(app.staticTexts["Wartet"].waitForExistence(timeout: 5))
    }

    @MainActor
    func testVerwerfenNachBestaetigung() {
        let app = starten()
        oeffnen(app, 3)
        XCTAssertTrue(app.buttons["detail.verwerfen"].waitForExistence(timeout: 10))
        app.buttons["detail.verwerfen"].tap()
        let dialog = app.alerts["Vorgang verwerfen?"]
        XCTAssertTrue(dialog.waitForExistence(timeout: 5))
        dialog.buttons["Verwerfen"].tap()
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: app.buttons["detail.verwerfen"])
        waitForExpectations(timeout: 10)
        XCTAssertTrue(app.staticTexts["Fehlgeschlagen"].waitForExistence(timeout: 5))
    }

    @MainActor
    func testKonfliktZeigtHinweisUndLaedtNach() {
        let app = starten()
        oeffnen(app, 7)
        XCTAssertTrue(app.buttons["detail.verwerfen"].waitForExistence(timeout: 10))
        app.buttons["detail.verwerfen"].tap()
        let dialog = app.alerts["Vorgang verwerfen?"]
        XCTAssertTrue(dialog.waitForExistence(timeout: 5))
        dialog.buttons["Verwerfen"].tap()
        let hinweis = app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'nicht mehr angehalten'")).firstMatch
        XCTAssertTrue(hinweis.waitForExistence(timeout: 10), "Hinweis zum 409 fehlt")
        // Der Stand wurde nachgeladen: Die Attrappe hat den Vorgang inzwischen als fertig geführt.
        XCTAssertFalse(app.buttons["detail.verwerfen"].exists)
        XCTAssertTrue(app.staticTexts["Fertig"].waitForExistence(timeout: 5))
    }
}
