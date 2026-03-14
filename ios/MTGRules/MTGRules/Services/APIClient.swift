import Foundation

enum APIError: LocalizedError {
    case invalidURL
    case networkError(Error)
    case decodingError(Error)
    case serverError(String)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Invalid server URL"
        case .networkError(let error):
            return "Network error: \(error.localizedDescription)"
        case .decodingError(let error):
            return "Failed to parse response: \(error.localizedDescription)"
        case .serverError(let message):
            return message
        }
    }
}

class APIClient {
    static let shared = APIClient()
    private let session: URLSession
    private let decoder: JSONDecoder

    var baseURL: String = ""

    private init() {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        self.session = URLSession(configuration: config)
        self.decoder = JSONDecoder()
    }

    // MARK: - Cards

    func autocomplete(query: String) async throws -> [String] {
        guard query.count >= 2 else { return [] }
        return try await get("/api/cards/autocomplete?q=\(query.urlEncoded)")
    }

    func searchCards(query: String, limit: Int = 12) async throws -> [Card] {
        return try await get("/api/cards/search?q=\(query.urlEncoded)&limit=\(limit)")
    }

    func getCard(name: String) async throws -> Card {
        return try await get("/api/cards/\(name.urlEncoded)")
    }

    // MARK: - Rules

    func searchRules(query: String, limit: Int = 25) async throws -> [Rule] {
        return try await get("/api/rules/search?q=\(query.urlEncoded)&limit=\(limit)")
    }

    // MARK: - Interactions

    func analyzeInteraction(cardNames: [String], format: String = "all") async throws -> InteractionResult {
        let body = InteractionQuery(cardNames: cardNames, format: format)
        return try await post("/api/interactions/analyze", body: body)
    }

    // MARK: - Board

    func analyzeBoard(board: BoardState, event: GameEvent) async throws -> BoardAnalysisResult {
        let body = BoardAnalysisRequest(board: board, event: event)
        return try await post("/api/board/analyze", body: body)
    }

    // MARK: - Chat

    func chat(question: String, history: [ChatMessage]) async throws -> String {
        let historyMessages = history.map { ChatHistoryMessage(role: $0.role, content: $0.content) }
        let body = ChatRequest(question: question, history: historyMessages)
        let response: ChatResponse = try await post("/api/chat/ask", body: body)
        return response.answer
    }

    // MARK: - HTTP

    private func get<T: Decodable>(_ path: String) async throws -> T {
        guard let url = URL(string: baseURL + path) else {
            throw APIError.invalidURL
        }
        do {
            let (data, response) = try await session.data(from: url)
            try checkResponse(response, data: data)
            return try decoder.decode(T.self, from: data)
        } catch let error as APIError {
            throw error
        } catch let error as DecodingError {
            throw APIError.decodingError(error)
        } catch {
            throw APIError.networkError(error)
        }
    }

    private func post<T: Decodable, B: Encodable>(_ path: String, body: B) async throws -> T {
        guard let url = URL(string: baseURL + path) else {
            throw APIError.invalidURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)

        do {
            let (data, response) = try await session.data(for: request)
            try checkResponse(response, data: data)
            return try decoder.decode(T.self, from: data)
        } catch let error as APIError {
            throw error
        } catch let error as DecodingError {
            throw APIError.decodingError(error)
        } catch {
            throw APIError.networkError(error)
        }
    }

    private func checkResponse(_ response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { return }
        guard (200...299).contains(http.statusCode) else {
            if let detail = try? JSONDecoder().decode([String: String].self, from: data),
               let message = detail["detail"] {
                throw APIError.serverError(message)
            }
            throw APIError.serverError("Server error: \(http.statusCode)")
        }
    }
}

extension String {
    var urlEncoded: String {
        self.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? self
    }
}
