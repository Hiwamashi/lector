import XCTest

/// Übergabe aus Scanner und Fotoauswahl gegen den Attrappen-Dienst. Kamera und Fotoauswahl sind im
/// Simulator nicht brauchbar; das Startargument `-UITEST_TESTBILD` stellt dafür den Eintrag
/// „Testbild übergeben“ bereit, der drei erzeugte Bilder übergibt.
final class ErfassungUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    @MainActor
    private func starten(_ zusatz: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-UITEST_ATTRAPPE", "-UITEST_ADRESSE_GESETZT", "-UITEST_ANGEMELDET",
                               "-UITEST_AUTH_MODUS", "paperless", "-UITEST_TESTBILD"] + zusatz
        app.launch()
        return app
    }

    @MainActor
    private func testbildUebergeben(_ app: XCUIApplication) {
        let menue = app.buttons["haupt.hinzufuegen"]
        XCTAssertTrue(menue.waitForExistence(timeout: 10), "Menü „Beleg übergeben“ fehlt")
        menue.tap()
        // „Beleg scannen“ steht nur da, wo `VNDocumentCameraViewController.isSupported` gilt; der Simulator
        // meldet es teils trotzdem, darum wird es hier nicht geprüft.
        XCTAssertTrue(app.buttons["haupt.fotos"].exists)
        let testbild = app.buttons["haupt.testbild"]
        XCTAssertTrue(testbild.waitForExistence(timeout: 5))
        testbild.tap()
    }

    @MainActor
    func testUebergabeWirdBestaetigt() {
        let app = starten()
        testbildUebergeben(app)
        XCTAssertTrue(app.descendants(matching: .any)["erfassung.uebergeben"].waitForExistence(timeout: 15),
                      "Bestätigung fehlt")
        XCTAssertFalse(app.buttons["erfassung.erneut"].exists)
        app.buttons["erfassung.schliessen"].tap()
        XCTAssertTrue(app.buttons["historie.zeile.7"].waitForExistence(timeout: 10), "Historie nach dem Schließen sichtbar")
    }

    @MainActor
    func testFehlschlagBietetErneutSendenAn() {
        let app = starten(["-UITEST_UPLOAD_FEHLER"])
        testbildUebergeben(app)
        XCTAssertTrue(app.descendants(matching: .any)["erfassung.fehler"].waitForExistence(timeout: 15), "Fehlermeldung fehlt")
        XCTAssertFalse(app.descendants(matching: .any)["erfassung.uebergeben"].exists)
        let erneut = app.buttons["erfassung.erneut"]
        XCTAssertTrue(erneut.exists)
        erneut.tap()
        XCTAssertTrue(app.descendants(matching: .any)["erfassung.uebergeben"].waitForExistence(timeout: 15),
                      "Erneutes Senden hat nicht übergeben")
    }

    @MainActor
    func testAblehnungDurchDenDienstWirdAngezeigt() {
        let app = starten(["-UITEST_UPLOAD_ABGELEHNT"])
        testbildUebergeben(app)
        let abgewiesen = app.descendants(matching: .any)["erfassung.abgewiesen"]
        XCTAssertTrue(abgewiesen.waitForExistence(timeout: 15), "Ablehnung wird nicht angezeigt")
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'Dateiformat wird nicht unterstützt'")).firstMatch.exists)
        XCTAssertFalse(app.buttons["erfassung.erneut"].exists, "Bei Ablehnung hilft erneutes Senden nicht")
    }
}
