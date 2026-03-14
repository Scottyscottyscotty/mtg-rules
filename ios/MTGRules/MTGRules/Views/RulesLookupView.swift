import SwiftUI

struct RulesLookupView: View {
    @StateObject private var vm = RulesViewModel()

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // Search bar
                HStack {
                    TextField("Search rules (e.g. 'stack', 'trample')", text: $vm.searchText)
                        .textFieldStyle(.roundedBorder)
                        .submitLabel(.search)
                        .onSubmit { Task { await vm.search() } }

                    Button {
                        Task { await vm.search() }
                    } label: {
                        Image(systemName: "magnifyingglass")
                            .foregroundColor(.white)
                            .padding(10)
                            .background(Color("AccentRed"))
                            .cornerRadius(8)
                    }
                }
                .padding()

                if vm.isLoading {
                    Spacer()
                    ProgressView()
                        .tint(Color("AccentRed"))
                    Spacer()
                } else if let error = vm.error {
                    Spacer()
                    Text(error)
                        .foregroundColor(Color("AccentRed"))
                        .padding()
                    Spacer()
                } else if vm.rules.isEmpty {
                    Spacer()
                    VStack(spacing: 8) {
                        Image(systemName: "book")
                            .font(.largeTitle)
                            .foregroundColor(.secondary)
                        Text("Search the comprehensive rules")
                            .foregroundColor(.secondary)
                    }
                    Spacer()
                } else {
                    List(vm.rules) { rule in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(rule.number)
                                .font(.caption)
                                .fontWeight(.bold)
                                .foregroundColor(Color("AccentRed"))
                            Text(rule.text)
                                .font(.subheadline)
                        }
                        .listRowBackground(Color("CardBackground"))
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                }
            }
            .background(Color("Background"))
            .navigationTitle("Rules Lookup")
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}
