import SwiftUI

/// Die Farbrollen der App aus `DESIGN.md`: ein Akzent (Werkstatt-Petrol) und vier Signalfarben.
/// Der Rohwert ist der Name des Color Sets in `Farben.xcassets`; Hell/Dunkel löst das System auf.
///
/// Der einzige Weg zu einer eigenen Farbe in der App — keine Hex-Werte, kein `Color("…")`
/// außerhalb dieser Datei. Flächen und Text nutzen sonst die Systemfarben. Der Zustand wird
/// immer zusätzlich zur Farbe beschriftet, nie über Farbe allein.
enum Farbe: String, CaseIterable, Sendable {
    case akzent, akzentAuf, akzentHauch
    case textLeise
    case gruen, gruenFlaeche
    case amber, amberFlaeche
    case rot, rotFlaeche
    case violett, violettFlaeche

    var color: Color { Color(rawValue, bundle: .main) }
}

extension ShapeStyle where Self == Color {
    static var akzent: Color { Farbe.akzent.color }
    static var akzentAuf: Color { Farbe.akzentAuf.color }
    static var akzentHauch: Color { Farbe.akzentHauch.color }
    static var textLeise: Color { Farbe.textLeise.color }
    static var gruen: Color { Farbe.gruen.color }
    static var gruenFlaeche: Color { Farbe.gruenFlaeche.color }
    static var amber: Color { Farbe.amber.color }
    static var amberFlaeche: Color { Farbe.amberFlaeche.color }
    static var rot: Color { Farbe.rot.color }
    static var rotFlaeche: Color { Farbe.rotFlaeche.color }
    static var violett: Color { Farbe.violett.color }
    static var violettFlaeche: Color { Farbe.violettFlaeche.color }
}

extension DokumentZustand {
    /// Signalfarbe und Fläche des Zustands wie die Badges der Weboberfläche (DESIGN.md, „Status-Badges“).
    var farben: (vordergrund: Farbe, flaeche: Farbe) {
        switch self {
        case .pending: (.amber, .amberFlaeche)
        case .processing, .skippedErechnung: (.akzent, .akzentHauch)
        case .blocked: (.violett, .violettFlaeche)
        case .done: (.gruen, .gruenFlaeche)
        case .failed: (.rot, .rotFlaeche)
        }
    }
}
