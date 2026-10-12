import Foundation
import Testing
@testable import Lector

@Suite("Projektgerüst")
struct GeruestTests {
    @Test("Testziel ist an die App gebunden")
    func appIstErreichbar() {
        #expect(Bundle.main.bundleIdentifier != nil)
        #expect(ServerKonfiguration.appGruppe == "group.me.krinke.lector")
    }
}
