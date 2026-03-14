import SwiftUI

struct CardSearchView: View {
    @StateObject private var vm = CardSearchViewModel()

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // Search bar
                HStack {
                    TextField("Search cards...", text: $vm.searchText)
                        .textFieldStyle(.roundedBorder)
                        .submitLabel(.search)
                        .onChange(of: vm.searchText) { _, newValue in
                            vm.fetchAutocomplete(query: newValue)
                        }
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

                // Autocomplete
                if !vm.searchText.isEmpty && !vm.autocompleteSuggestions.isEmpty {
                    ScrollView {
                        VStack(spacing: 0) {
                            ForEach(vm.autocompleteSuggestions.prefix(8), id: \.self) { name in
                                Button {
                                    vm.searchText = name
                                    vm.autocompleteSuggestions = []
                                    Task { await vm.search() }
                                } label: {
                                    HStack {
                                        Text(name)
                                            .foregroundColor(.white)
                                        Spacer()
                                    }
                                    .padding(.horizontal, 16)
                                    .padding(.vertical, 12)
                                }
                                Divider().background(Color("Border"))
                            }
                        }
                        .background(Color("CardBackground"))
                        .cornerRadius(8)
                        .padding(.horizontal)
                    }
                    .frame(maxHeight: 300)
                }

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
                } else {
                    // Results
                    ScrollView {
                        LazyVStack(spacing: 12) {
                            ForEach(vm.cards) { card in
                                CardRow(card: card)
                            }
                        }
                        .padding()
                    }
                }
            }
            .background(Color("Background"))
            .navigationTitle("Card Search")
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}

struct CardRow: View {
    let card: Card
    @State private var isExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            // Header - always visible
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(card.name)
                        .font(.headline)
                        .foregroundColor(Color("AccentRed"))
                    Text(card.typeLine)
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                Spacer()
                if let cost = card.manaCost, !cost.isEmpty {
                    Text(cost)
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                    .foregroundColor(.secondary)
                    .font(.caption)
            }

            if isExpanded {
                // Card image
                if let imageUri = card.imageUri, let url = URL(string: imageUri) {
                    AsyncImage(url: url) { phase in
                        switch phase {
                        case .success(let image):
                            image
                                .resizable()
                                .aspectRatio(contentMode: .fit)
                                .cornerRadius(8)
                        case .failure:
                            EmptyView()
                        default:
                            ProgressView()
                                .frame(height: 200)
                        }
                    }
                }

                // Oracle text
                if let text = card.oracleText, !text.isEmpty {
                    Text(text)
                        .font(.subheadline)
                        .padding(8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color("InputBackground"))
                        .cornerRadius(6)
                }

                // Keywords
                if !card.keywords.isEmpty {
                    FlowLayout(spacing: 4) {
                        ForEach(card.keywords, id: \.self) { keyword in
                            Text(keyword)
                                .font(.caption2)
                                .padding(.horizontal, 8)
                                .padding(.vertical, 4)
                                .background(Color("AccentRed").opacity(0.2))
                                .cornerRadius(10)
                        }
                    }
                }

                // Rulings
                if !card.rulings.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Rulings")
                            .font(.caption)
                            .fontWeight(.semibold)
                            .foregroundColor(Color("AccentRed"))
                        ForEach(Array(card.rulings.prefix(5).enumerated()), id: \.offset) { _, ruling in
                            Text(ruling)
                                .font(.caption2)
                                .foregroundColor(.secondary)
                        }
                    }
                }
            }
        }
        .padding()
        .background(Color("CardBackground"))
        .cornerRadius(12)
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(Color("Border"), lineWidth: 1)
        )
        .onTapGesture { withAnimation { isExpanded.toggle() } }
    }
}
