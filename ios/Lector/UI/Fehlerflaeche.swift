import SwiftUI

/// Meldung als eingelassene Fläche mit Linie: Rot für Fehler, Akzent für Hinweise. Immer mit Text,
/// nie nur Farbe.
struct Fehlerflaeche: View {
    enum Art { case fehler, hinweis }

    let text: String
    var art: Art = .fehler

    private var vordergrund: Color { art == .fehler ? .rot : .akzent }
    private var flaeche: Color { art == .fehler ? .rotFlaeche : .akzentHauch }

    var body: some View {
        Label {
            Text(text).font(.callout).foregroundStyle(.primary)
        } icon: {
            Image(systemName: art == .fehler ? "exclamationmark.triangle.fill" : "info.circle.fill")
                .foregroundStyle(vordergrund)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(flaeche, in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(vordergrund.opacity(0.5), lineWidth: 1))
    }
}
