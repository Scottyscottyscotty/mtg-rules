import SwiftUI

@MainActor
class BoardViewModel: ObservableObject {
    @Published var players: [PlayerState] = []
    @Published var activePlayer = ""
    @Published var selectedEventType = "cast_spell"
    @Published var eventSourceCard = ""
    @Published var eventSourcePlayer = ""
    @Published var eventDetails = ""
    @Published var result: BoardAnalysisResult?
    @Published var isLoading = false
    @Published var error: String?
    @Published var showPlainEnglish = true

    // Autocomplete
    @Published var autocompleteSuggestions: [String] = []
    private var autocompleteTask: Task<Void, Never>?

    let eventTypes: [(String, String)] = [
        ("cast_spell", "Cast Spell"),
        ("enters_battlefield", "Enters Battlefield"),
        ("dies", "Dies"),
        ("sacrifice", "Sacrifice"),
        ("draw_card", "Draw Card"),
        ("damage_dealt", "Damage Dealt"),
        ("gain_life", "Gain Life"),
        ("lose_life", "Lose Life"),
        ("discard", "Discard"),
        ("attacks", "Attacks"),
        ("blocks", "Blocks"),
        ("create_token", "Create Token"),
        ("activate_ability", "Activate Ability"),
        ("leaves_battlefield", "Leaves Battlefield"),
        ("upkeep", "Upkeep"),
        ("end_step", "End Step"),
    ]

    func addPlayer(name: String) {
        guard !name.isEmpty, !players.contains(where: { $0.name == name }) else { return }
        players.append(PlayerState(name: name, life: 40, permanents: []))
        if activePlayer.isEmpty { activePlayer = name }
    }

    func removePlayer(at index: Int) {
        players.remove(at: index)
    }

    func addPermanent(to playerIndex: Int, cardName: String) {
        guard !cardName.isEmpty else { return }
        let player = players[playerIndex]
        let permanent = PermanentOnBoard(
            cardName: cardName,
            owner: player.name,
            controller: player.name,
            tapped: false
        )
        players[playerIndex].permanents.append(permanent)
    }

    func removePermanent(from playerIndex: Int, at permIndex: Int) {
        players[playerIndex].permanents.remove(at: permIndex)
    }

    func fetchAutocomplete(query: String) {
        autocompleteTask?.cancel()
        guard query.count >= 2 else {
            autocompleteSuggestions = []
            return
        }
        autocompleteTask = Task {
            try? await Task.sleep(nanoseconds: 150_000_000)
            guard !Task.isCancelled else { return }
            do {
                let suggestions = try await APIClient.shared.autocomplete(query: query)
                if !Task.isCancelled {
                    self.autocompleteSuggestions = suggestions
                }
            } catch {
                // Silently fail autocomplete
            }
        }
    }

    func analyzeEvent() async {
        guard !players.isEmpty else { return }
        isLoading = true
        error = nil
        result = nil

        let board = BoardState(
            players: players,
            activePlayer: activePlayer.isEmpty ? players.first?.name : activePlayer
        )
        let event = GameEvent(
            eventType: selectedEventType,
            sourceCard: eventSourceCard.isEmpty ? nil : eventSourceCard,
            sourcePlayer: eventSourcePlayer.isEmpty ? nil : eventSourcePlayer,
            details: eventDetails
        )

        do {
            result = try await APIClient.shared.analyzeBoard(board: board, event: event)
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
    }
}
