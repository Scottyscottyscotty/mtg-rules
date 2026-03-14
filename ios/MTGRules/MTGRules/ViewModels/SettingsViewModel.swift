import SwiftUI

class SettingsViewModel: ObservableObject {
    @AppStorage("serverURL") var serverURL: String = "" {
        didSet {
            APIClient.shared.baseURL = serverURL
        }
    }

    init() {
        APIClient.shared.baseURL = serverURL
    }
}
