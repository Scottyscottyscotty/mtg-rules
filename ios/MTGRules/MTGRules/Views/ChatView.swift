import SwiftUI

struct ChatView: View {
    @StateObject private var vm = ChatViewModel()

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // Messages
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 12) {
                            // Welcome message
                            if vm.messages.isEmpty {
                                welcomeMessage
                            }

                            ForEach(vm.messages) { message in
                                ChatBubble(message: message)
                                    .id(message.id)
                            }

                            if vm.isLoading {
                                HStack {
                                    ProgressView()
                                        .tint(Color("AccentRed"))
                                    Text("Looking up rules...")
                                        .foregroundColor(.secondary)
                                        .font(.caption)
                                    Spacer()
                                }
                                .padding(.horizontal)
                                .id("loading")
                            }
                        }
                        .padding()
                    }
                    .onChange(of: vm.messages.count) {
                        withAnimation {
                            proxy.scrollTo(vm.messages.last?.id ?? "loading", anchor: .bottom)
                        }
                    }
                }

                // Error
                if let error = vm.error {
                    Text(error)
                        .font(.caption)
                        .foregroundColor(Color("AccentRed"))
                        .padding(.horizontal)
                }

                // Input
                HStack(spacing: 8) {
                    TextField("Ask a rules question...", text: $vm.inputText)
                        .textFieldStyle(.roundedBorder)
                        .submitLabel(.send)
                        .onSubmit {
                            Task { await vm.sendMessage() }
                        }

                    Button {
                        Task { await vm.sendMessage() }
                    } label: {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.title2)
                            .foregroundColor(
                                vm.inputText.trimmingCharacters(in: .whitespaces).isEmpty
                                    ? .secondary : Color("AccentRed")
                            )
                    }
                    .disabled(vm.inputText.trimmingCharacters(in: .whitespaces).isEmpty || vm.isLoading)
                }
                .padding()
                .background(Color("CardBackground"))
            }
            .background(Color("Background"))
            .navigationTitle("Rules Chat")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    private var welcomeMessage: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Ask me anything about MTG rules!")
                .font(.headline)
                .foregroundColor(.white)

            VStack(alignment: .leading, spacing: 4) {
                suggestionButton("What does poison do?")
                suggestionButton("Can two same-name legendaries be on the board?")
                suggestionButton("How does Rhystic Study work?")
                suggestionButton("What happens with deathtouch + trample?")
            }
        }
        .padding()
        .background(Color("InputBackground"))
        .cornerRadius(12)
    }

    private func suggestionButton(_ text: String) -> some View {
        Button {
            vm.inputText = text
            Task { await vm.sendMessage() }
        } label: {
            HStack {
                Image(systemName: "bubble.left")
                    .font(.caption)
                Text(text)
                    .font(.subheadline)
                Spacer()
            }
            .foregroundColor(Color("AccentRed"))
            .padding(.vertical, 4)
        }
    }
}

struct ChatBubble: View {
    let message: ChatMessage

    var isUser: Bool { message.role == "user" }

    var body: some View {
        HStack {
            if isUser { Spacer(minLength: 40) }

            Text(message.content)
                .font(.subheadline)
                .padding(12)
                .background(isUser ? Color("AccentRed") : Color("InputBackground"))
                .foregroundColor(.white)
                .cornerRadius(16, corners: isUser
                    ? [.topLeading, .topTrailing, .bottomLeading]
                    : [.topLeading, .topTrailing, .bottomTrailing])

            if !isUser { Spacer(minLength: 40) }
        }
    }
}

// Custom corner radius
extension View {
    func cornerRadius(_ radius: CGFloat, corners: UIRectCorner) -> some View {
        clipShape(RoundedCornerShape(radius: radius, corners: corners))
    }
}

struct RoundedCornerShape: Shape {
    var radius: CGFloat
    var corners: UIRectCorner

    func path(in rect: CGRect) -> Path {
        let path = UIBezierPath(
            roundedRect: rect,
            byRoundingCorners: corners,
            cornerRadii: CGSize(width: radius, height: radius)
        )
        return Path(path.cgPath)
    }
}
