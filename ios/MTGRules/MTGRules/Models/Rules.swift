import Foundation

struct Rule: Codable, Identifiable {
    var id: String { number }
    let number: String
    let text: String
}

struct ChatMessage: Codable, Identifiable {
    let id: UUID
    let role: String
    let content: String

    init(role: String, content: String) {
        self.id = UUID()
        self.role = role
        self.content = content
    }

    enum CodingKeys: String, CodingKey {
        case role, content
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.id = UUID()
        self.role = try container.decode(String.self, forKey: .role)
        self.content = try container.decode(String.self, forKey: .content)
    }
}

struct ChatRequest: Codable {
    let question: String
    let history: [ChatHistoryMessage]
}

struct ChatHistoryMessage: Codable {
    let role: String
    let content: String
}

struct ChatResponse: Codable {
    let answer: String
}
