import Foundation
import UniformTypeIdentifiers

/// Eine geteilte Datei als `NSItemProvider` der Share Extension.
struct ItemProviderQuelle: TeilenQuelle, @unchecked Sendable {
    let provider: NSItemProvider

    var dateiname: String { provider.suggestedName ?? "Dokument" }

    var typen: [UTType] { provider.registeredTypeIdentifiers.compactMap { UTType($0) } }

    /// Der Provider gibt die Datei nur während des Rückrufs frei; darum wird dort kopiert.
    func kopieren(typ: UTType, nach ziel: URL) async throws -> URL {
        try await withCheckedThrowingContinuation { fortsetzung in
            provider.loadFileRepresentation(forTypeIdentifier: typ.identifier) { url, fehler in
                guard let url else {
                    fortsetzung.resume(throwing: fehler ?? CocoaError(.fileReadUnknown))
                    return
                }
                do {
                    let kopie = ziel.appendingPathComponent(url.lastPathComponent)
                    try FileManager.default.copyItem(at: url, to: kopie)
                    fortsetzung.resume(returning: kopie)
                } catch {
                    fortsetzung.resume(throwing: error)
                }
            }
        }
    }
}
