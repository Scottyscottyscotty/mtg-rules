import SwiftUI

@main
struct MTGRulesApp: App {
    @StateObject private var settingsViewModel = SettingsViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(settingsViewModel)
                .preferredColorScheme(.dark)
        }
    }
}
