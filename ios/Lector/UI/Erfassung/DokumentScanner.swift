import SwiftUI
import VisionKit

/// Der Dokumentenscanner des Systems (Kantenerkennung, mehrere Seiten je Beleg) als SwiftUI-Ansicht.
/// Auf dem Simulator gibt es keine Kamera: dort ist `unterstuetzt` false und der Eintrag entfällt.
struct DokumentScanner: UIViewControllerRepresentable {
    static var unterstuetzt: Bool { VNDocumentCameraViewController.isSupported }

    /// Die gescannten Seiten, in Aufnahmereihenfolge.
    let fertig: ([UIImage]) -> Void
    let abgebrochen: () -> Void

    func makeCoordinator() -> Koordinator { Koordinator(fertig: fertig, abgebrochen: abgebrochen) }

    func makeUIViewController(context: Context) -> VNDocumentCameraViewController {
        let controller = VNDocumentCameraViewController()
        controller.delegate = context.coordinator
        return controller
    }

    func updateUIViewController(_ controller: VNDocumentCameraViewController, context: Context) {}

    final class Koordinator: NSObject, VNDocumentCameraViewControllerDelegate {
        let fertig: ([UIImage]) -> Void
        let abgebrochen: () -> Void

        init(fertig: @escaping ([UIImage]) -> Void, abgebrochen: @escaping () -> Void) {
            self.fertig = fertig
            self.abgebrochen = abgebrochen
        }

        func documentCameraViewController(
            _ controller: VNDocumentCameraViewController, didFinishWith scan: VNDocumentCameraScan
        ) {
            fertig((0..<scan.pageCount).map { scan.imageOfPage(at: $0) })
        }

        func documentCameraViewControllerDidCancel(_ controller: VNDocumentCameraViewController) {
            abgebrochen()
        }

        func documentCameraViewController(_ controller: VNDocumentCameraViewController, didFailWithError error: Error) {
            abgebrochen()
        }
    }
}
