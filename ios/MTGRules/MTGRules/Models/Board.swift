import Foundation

struct PermanentOnBoard: Codable, Identifiable, Hashable {
    var id: String { cardName + owner }
    let cardName: String
    let owner: String
    var controller: String?
    var tapped: Bool = false

    enum CodingKeys: String, CodingKey {
        case cardName = "card_name"
        case owner, controller, tapped
    }
}

struct PlayerState: Codable, Identifiable, Hashable {
    var id: String { name }
    var name: String
    var life: Int = 40
    var permanents: [PermanentOnBoard] = []
}

struct GameEvent: Codable {
    let eventType: String
    var sourceCard: String?
    var sourcePlayer: String?
    var targetCard: String?
    var targetPlayer: String?
    var details: String = ""

    enum CodingKeys: String, CodingKey {
        case eventType = "event_type"
        case sourceCard = "source_card"
        case sourcePlayer = "source_player"
        case targetCard = "target_card"
        case targetPlayer = "target_player"
        case details
    }
}

struct BoardState: Codable {
    var players: [PlayerState] = []
    var activePlayer: String?

    enum CodingKeys: String, CodingKey {
        case players
        case activePlayer = "active_player"
    }
}

struct BoardAnalysisRequest: Codable {
    let board: BoardState
    let event: GameEvent
}

struct DetectedTrigger: Codable, Identifiable {
    var id: String { permanentName + triggerText }
    let permanentName: String
    let controller: String
    let triggerText: String

    enum CodingKeys: String, CodingKey {
        case permanentName = "permanent_name"
        case controller
        case triggerText = "trigger_text"
    }
}

struct ReplacementEffect: Codable, Identifiable {
    var id: String { permanentName + replacementText }
    let permanentName: String
    let controller: String
    let replacementText: String

    enum CodingKeys: String, CodingKey {
        case permanentName = "permanent_name"
        case controller
        case replacementText = "replacement_text"
    }
}

struct CascadeStep: Codable, Identifiable {
    var id: Int { stepNumber }
    let stepNumber: Int
    let event: GameEvent
    let triggersFired: [DetectedTrigger]
    let replacementsApplied: [ReplacementEffect]
    let notes: [String]

    enum CodingKeys: String, CodingKey {
        case stepNumber = "step_number"
        case event
        case triggersFired = "triggers_fired"
        case replacementsApplied = "replacements_applied"
        case notes
    }
}

struct BoardAnalysisResult: Codable {
    let originalEvent: GameEvent
    let cascade: [CascadeStep]
    let stackOrder: [String]
    let warnings: [String]
    let summary: String
    let plainEnglish: String

    enum CodingKeys: String, CodingKey {
        case originalEvent = "original_event"
        case cascade
        case stackOrder = "stack_order"
        case warnings, summary
        case plainEnglish = "plain_english"
    }
}
