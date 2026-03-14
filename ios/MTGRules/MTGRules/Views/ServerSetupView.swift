import SwiftUI

struct ServerSetupView: View {
    @EnvironmentObject var settings: SettingsViewModel
    @State private var urlInput = "http://"
    @State private var isChecking = false
    @State private var error: String?

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            Text("MTG")
                .font(.system(size: 48, weight: .bold))
                .foregroundColor(Color("AccentRed"))
            + Text(" Rules Engine")
                .font(.system(size: 48, weight: .light))
                .foregroundColor(.white)

            Text("Connect to your server to get started")
                .foregroundColor(.secondary)

            VStack(spacing: 12) {
                TextField("Server URL (e.g. http://192.168.1.5:8000)", text: $urlInput)
                    .textFieldStyle(.roundedBorder)
                    .autocapitalization(.none)
                    .disableAutocorrection(true)
                    .keyboardType(.URL)

                if let error {
                    Text(error)
                        .foregroundColor(Color("AccentRed"))
                        .font(.caption)
                }

                Button {
                    connect()
                } label: {
                    if isChecking {
                        ProgressView()
                            .tint(.white)
                    } else {
                        Text("Connect")
                    }
                }
                .frame(maxWidth: .infinity)
                .padding()
                .background(Color("AccentRed"))
                .foregroundColor(.white)
                .cornerRadius(12)
                .disabled(isChecking)
            }
            .padding(.horizontal, 32)

            Spacer()

            Text("Make sure your server is running:\npython run.py")
                .font(.caption)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .padding(.bottom, 32)
        }
        .background(Color("Background"))
    }

    private func connect() {
        var url = urlInput.trimmingCharacters(in: .whitespacesAndNewlines)
        if url.hasSuffix("/") { url.removeLast() }
        guard !url.isEmpty else { return }

        isChecking = true
        error = nil

        Task {
            // Quick health check
            guard let testURL = URL(string: url + "/docs") else {
                error = "Invalid URL"
                isChecking = false
                return
            }
            do {
                let (_, response) = try await URLSession.shared.data(from: testURL)
                if let http = response as? HTTPURLResponse, (200...399).contains(http.statusCode) {
                    settings.serverURL = url
                } else {
                    error = "Server not responding. Is it running?"
                }
            } catch {
                self.error = "Can't reach server: \(error.localizedDescription)"
            }
            isChecking = false
        }
    }
}
