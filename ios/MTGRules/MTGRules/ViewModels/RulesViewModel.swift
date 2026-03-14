import SwiftUI

@MainActor
class RulesViewModel: ObservableObject {
    @Published var searchText = ""
    @Published var rules: [Rule] = []
    @Published var isLoading = false
    @Published var error: String?

    func search() async {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return }

        isLoading = true
        error = nil

        do {
            rules = try await APIClient.shared.searchRules(query: query)
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
    }
}
