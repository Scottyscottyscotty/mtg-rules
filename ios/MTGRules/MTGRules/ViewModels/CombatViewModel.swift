import SwiftUI

@MainActor
class CombatViewModel: ObservableObject {
    @Published var assignments: [CombatBlockAssignment] = []
    @Published var defendingPlayer = "Opponent"
    @Published var result: CombatSimResult?
    @Published var isLoading = false
    @Published var error: String?

    // Autocomplete
    @Published var autocompleteSuggestions: [String] = []
    private var autocompleteTask: Task<Void, Never>?

    func addAttacker() {
        assignments.append(CombatBlockAssignment(
            attacker: CombatCreatureInput(cardName: "", controller: "You"),
            blockers: []
        ))
    }

    func removeAttacker(at index: Int) {
        assignments.remove(at: index)
    }

    func addBlocker(to attackerIndex: Int) {
        assignments[attackerIndex].blockers.append(
            CombatCreatureInput(cardName: "", controller: "Opponent")
        )
    }

    func removeBlocker(from attackerIndex: Int, at blockerIndex: Int) {
        assignments[attackerIndex].blockers.remove(at: blockerIndex)
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
            } catch {}
        }
    }

    func simulateCombat() async {
        let validAssignments = assignments.filter { !$0.attacker.cardName.isEmpty }
        guard !validAssignments.isEmpty else { return }

        isLoading = true
        error = nil
        result = nil

        let request = CombatSimRequest(
            assignments: validAssignments,
            defendingPlayer: defendingPlayer.isEmpty ? "Opponent" : defendingPlayer
        )

        do {
            result = try await APIClient.shared.simulateCombat(request: request)
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
    }
}
