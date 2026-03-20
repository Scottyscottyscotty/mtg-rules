import SwiftUI

struct ContentView: View {
    @EnvironmentObject var settings: SettingsViewModel
    @State private var selectedTab = 0

    var body: some View {
        if settings.serverURL.isEmpty {
            ServerSetupView()
        } else {
            TabView(selection: $selectedTab) {
                ChatView()
                    .tabItem {
                        Label("Chat", systemImage: "bubble.left.and.bubble.right")
                    }
                    .tag(0)

                BoardStateView()
                    .tabItem {
                        Label("Board", systemImage: "square.grid.3x3")
                    }
                    .tag(1)

                CombatView()
                    .tabItem {
                        Label("Combat", systemImage: "shield.lefthalf.filled")
                    }
                    .tag(2)

                CardSearchView()
                    .tabItem {
                        Label("Cards", systemImage: "rectangle.stack")
                    }
                    .tag(3)

                RulesLookupView()
                    .tabItem {
                        Label("Rules", systemImage: "book")
                    }
                    .tag(4)

                SettingsView()
                    .tabItem {
                        Label("Settings", systemImage: "gear")
                    }
                    .tag(5)
            }
            .tint(Color("AccentRed"))
        }
    }
}
