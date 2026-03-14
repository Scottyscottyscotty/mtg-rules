import SwiftUI

@MainActor
class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var inputText = ""
    @Published var isLoading = false
    @Published var error: String?

    func sendMessage() async {
        let question = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !question.isEmpty else { return }

        inputText = ""
        error = nil

        let userMessage = ChatMessage(role: "user", content: question)
        messages.append(userMessage)
        isLoading = true

        do {
            let answer = try await APIClient.shared.chat(
                question: question,
                history: messages.filter { $0.role == "user" || $0.role == "assistant" }
            )
            let assistantMessage = ChatMessage(role: "assistant", content: answer)
            messages.append(assistantMessage)
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
    }
}
