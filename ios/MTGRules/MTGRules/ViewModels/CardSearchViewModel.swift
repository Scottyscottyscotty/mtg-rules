import SwiftUI

@MainActor
class CardSearchViewModel: ObservableObject {
    @Published var searchText = ""
    @Published var cards: [Card] = []
    @Published var isLoading = false
    @Published var error: String?
    @Published var autocompleteSuggestions: [String] = []

    private var autocompleteTask: Task<Void, Never>?

    func search() async {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return }

        isLoading = true
        error = nil
        autocompleteSuggestions = []

        do {
            cards = try await APIClient.shared.searchCards(query: query)
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
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
}
