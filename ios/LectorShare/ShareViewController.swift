import SwiftUI
import UIKit

/// Einstieg der Share Extension: sammelt die geteilten Dateien, hängt die SwiftUI-Oberfläche ein
/// und beendet die Extension, wenn die Person schließt.
final class ShareViewController: UIViewController {
    private var modell: TeilenModell?

    override func viewDidLoad() {
        super.viewDidLoad()

        let konfiguration = ServerKonfiguration()
        let tokenStore = KeychainTokenStore()
        let transport = URLSessionTransport()
        let sitzung = AuthSession(konfiguration: konfiguration, transport: transport, tokenStore: tokenStore)
        let client = APIClient(konfiguration: konfiguration, transport: transport, sitzung: sitzung)

        let quellen = (extensionContext?.inputItems as? [NSExtensionItem] ?? [])
            .flatMap { $0.attachments ?? [] }
            .map { ItemProviderQuelle(provider: $0) }
        let modell = TeilenModell(quellen: quellen, client: client, konfiguration: konfiguration, tokenStore: tokenStore)
        self.modell = modell

        let inhalt = UIHostingController(rootView: TeilenAnsicht(modell: modell) { [weak self] in
            self?.beenden()
        })
        addChild(inhalt)
        inhalt.view.frame = view.bounds
        inhalt.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(inhalt.view)
        inhalt.didMove(toParent: self)
    }

    private func beenden() {
        modell?.aufraeumen()
        extensionContext?.completeRequest(returningItems: nil)
    }
}
