import Foundation

/// Kodierung der Schnittstelle (Anhang „Schnittstellenvertrag v1“): Schlüssel in `snake_case`,
/// Zeitpunkte als ISO-8601-Zeichenkette in UTC mit `Z`.
///
/// Lesen ist großzügig (mit und ohne Sekundenbruchteile, `Z` oder Offset), damit weder die
/// Python-Ausgabe mit Mikrosekunden noch eine Ausgabe ohne Bruchteil den Dekoder bricht.
enum JSONKodierung {
    static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .custom { decoder in
            let text = try decoder.singleValueContainer().decode(String.self)
            guard let datum = datum(aus: text) else {
                throw DecodingError.dataCorrupted(.init(
                    codingPath: decoder.codingPath,
                    debugDescription: "Kein ISO-8601-Zeitstempel: \(text)"))
            }
            return datum
        }
        return decoder
    }

    static func encoder() -> JSONEncoder {
        JSONEncoder()
    }

    static func datum(aus text: String) -> Date? {
        if let mitBruchteil = try? Date.ISO8601FormatStyle(includingFractionalSeconds: true).parse(text) {
            return mitBruchteil
        }
        return try? Date.ISO8601FormatStyle(includingFractionalSeconds: false).parse(text)
    }
}
