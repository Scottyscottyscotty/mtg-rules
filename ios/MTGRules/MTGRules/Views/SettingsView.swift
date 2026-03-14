import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var settings: SettingsViewModel

    var body: some View {
        NavigationStack {
            List {
                Section("Server") {
                    HStack {
                        Text("URL")
                        Spacer()
                        Text(settings.serverURL)
                            .foregroundColor(.secondary)
                            .lineLimit(1)
                    }
                    .listRowBackground(Color("CardBackground"))

                    Button("Disconnect") {
                        settings.serverURL = ""
                    }
                    .foregroundColor(Color("AccentRed"))
                    .listRowBackground(Color("CardBackground"))
                }

                Section("About") {
                    HStack {
                        Text("Version")
                        Spacer()
                        Text("1.0.0")
                            .foregroundColor(.secondary)
                    }
                    .listRowBackground(Color("CardBackground"))
                }
            }
            .listStyle(.insetGrouped)
            .scrollContentBackground(.hidden)
            .background(Color("Background"))
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}
