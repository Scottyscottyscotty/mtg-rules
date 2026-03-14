import Foundation

struct Card: Codable, Identifiable, Hashable {
    var id: String { name }
    let name: String
    let manaCost: String?
    let typeLine: String
    let oracleText: String?
    let colors: [String]
    let keywords: [String]
    let legalities: [String: String]
    let imageUri: String?
    let scryfallUri: String?
    let rulings: [String]

    enum CodingKeys: String, CodingKey {
        case name
        case manaCost = "mana_cost"
        case typeLine = "type_line"
        case oracleText = "oracle_text"
        case colors, keywords, legalities
        case imageUri = "image_uri"
        case scryfallUri = "scryfall_uri"
        case rulings
    }
}

struct InteractionQuery: Codable {
    let cardNames: [String]
    let format: String

    enum CodingKeys: String, CodingKey {
        case cardNames = "card_names"
        case format
    }
}

struct InteractionResult: Codable {
    let cards: [Card]
    let rulings: [String]
    let stackNotes: [String]
    let layerNotes: [String]
    let replacementNotes: [String]
    let summary: String

    enum CodingKeys: String, CodingKey {
        case cards, rulings
        case stackNotes = "stack_notes"
        case layerNotes = "layer_notes"
        case replacementNotes = "replacement_notes"
        case summary
    }
}
