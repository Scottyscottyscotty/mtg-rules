import SwiftUI

struct BoardStateView: View {
    @StateObject private var vm = BoardViewModel()
    @State private var newPlayerName = ""
    @State private var permanentInputs: [Int: String] = [:]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    // Add player
                    addPlayerSection

                    // Players
                    ForEach(Array(vm.players.enumerated()), id: \.element.name) { index, player in
                        playerCard(player: player, index: index)
                    }

                    // Event trigger
                    if !vm.players.isEmpty {
                        eventTriggerSection
                    }

                    // Results
                    if vm.isLoading {
                        ProgressView("Analyzing...")
                            .tint(Color("AccentRed"))
                            .padding()
                    }

                    if let error = vm.error {
                        Text(error)
                            .foregroundColor(Color("AccentRed"))
                            .padding()
                    }

                    if let result = vm.result {
                        resultSection(result)
                    }
                }
                .padding()
            }
            .background(Color("Background"))
            .navigationTitle("Board State")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    // MARK: - Add Player

    private var addPlayerSection: some View {
        HStack {
            TextField("Player name", text: $newPlayerName)
                .textFieldStyle(.roundedBorder)
                .submitLabel(.done)
                .onSubmit { addPlayer() }

            Button("Add") { addPlayer() }
                .buttonStyle(.borderedProminent)
                .tint(Color("AccentRed"))
                .disabled(newPlayerName.trimmingCharacters(in: .whitespaces).isEmpty)
        }
    }

    // MARK: - Player Card

    private func playerCard(player: PlayerState, index: Int) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            // Header
            HStack {
                Text(player.name)
                    .font(.headline)
                    .foregroundColor(Color("AccentRed"))

                Stepper("Life: \(player.life)", value: $vm.players[index].life)
                    .font(.caption)

                Spacer()

                Button("Remove") { vm.removePlayer(at: index) }
                    .font(.caption)
                    .foregroundColor(Color("AccentRed"))
            }

            // Add permanent with autocomplete
            HStack {
                ZStack(alignment: .topLeading) {
                    TextField("Add permanent", text: permanentBinding(for: index))
                        .textFieldStyle(.roundedBorder)
                        .onChange(of: permanentInputs[index] ?? "") { _, newValue in
                            vm.fetchAutocomplete(query: newValue)
                        }
                        .submitLabel(.done)
                        .onSubmit {
                            if let name = permanentInputs[index], !name.isEmpty {
                                vm.addPermanent(to: index, cardName: name)
                                permanentInputs[index] = ""
                                vm.autocompleteSuggestions = []
                            }
                        }
                }

                Button("Add") {
                    if let name = permanentInputs[index], !name.isEmpty {
                        vm.addPermanent(to: index, cardName: name)
                        permanentInputs[index] = ""
                        vm.autocompleteSuggestions = []
                    }
                }
                .buttonStyle(.borderedProminent)
                .tint(Color("AccentRed"))
            }

            // Autocomplete suggestions
            if !(permanentInputs[index] ?? "").isEmpty && !vm.autocompleteSuggestions.isEmpty {
                VStack(spacing: 0) {
                    ForEach(vm.autocompleteSuggestions.prefix(6), id: \.self) { suggestion in
                        Button {
                            vm.addPermanent(to: index, cardName: suggestion)
                            permanentInputs[index] = ""
                            vm.autocompleteSuggestions = []
                        } label: {
                            HStack {
                                Text(suggestion)
                                    .font(.subheadline)
                                    .foregroundColor(.white)
                                Spacer()
                            }
                            .padding(.horizontal, 12)
                            .padding(.vertical, 10)
                        }
                        Divider().background(Color("Border"))
                    }
                }
                .background(Color("InputBackground"))
                .cornerRadius(8)
            }

            // Permanents
            FlowLayout(spacing: 6) {
                ForEach(Array(player.permanents.enumerated()), id: \.offset) { permIndex, perm in
                    HStack(spacing: 4) {
                        Text(perm.cardName)
                            .font(.caption)
                        Button {
                            vm.removePermanent(from: index, at: permIndex)
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .font(.caption2)
                        }
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .background(Color("InputBackground"))
                    .overlay(
                        RoundedRectangle(cornerRadius: 16)
                            .stroke(Color("AccentRed"), lineWidth: 1)
                    )
                    .cornerRadius(16)
                    .foregroundColor(.white)
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
    }

    // MARK: - Event Trigger

    private var eventTriggerSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Trigger an Event")
                .font(.headline)

            Picker("Event", selection: $vm.selectedEventType) {
                ForEach(vm.eventTypes, id: \.0) { type in
                    Text(type.1).tag(type.0)
                }
            }
            .pickerStyle(.menu)
            .tint(Color("AccentRed"))

            TextField("Source card (optional)", text: $vm.eventSourceCard)
                .textFieldStyle(.roundedBorder)

            Picker("Source player", selection: $vm.eventSourcePlayer) {
                Text("-- select --").tag("")
                ForEach(vm.players, id: \.name) { player in
                    Text(player.name).tag(player.name)
                }
            }
            .pickerStyle(.menu)
            .tint(Color("AccentRed"))

            TextField("Details (e.g. 'creature spell')", text: $vm.eventDetails)
                .textFieldStyle(.roundedBorder)

            Button {
                Task { await vm.analyzeEvent() }
            } label: {
                HStack {
                    Spacer()
                    Text("Analyze Event")
                        .fontWeight(.semibold)
                    Spacer()
                }
            }
            .buttonStyle(.borderedProminent)
            .tint(Color("AccentRed"))
            .disabled(vm.isLoading)
        }
        .padding()
        .background(Color("CardBackground"))
        .cornerRadius(12)
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(Color("Border"), lineWidth: 1)
        )
    }

    // MARK: - Results

    private func resultSection(_ result: BoardAnalysisResult) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            // Toggle
            Picker("View", selection: $vm.showPlainEnglish) {
                Text("Plain English").tag(true)
                Text("Technical").tag(false)
            }
            .pickerStyle(.segmented)

            if vm.showPlainEnglish {
                Text(result.plainEnglish)
                    .font(.subheadline)
                    .lineSpacing(4)
                    .padding()
                    .background(Color("InputBackground"))
                    .cornerRadius(8)
            } else {
                Text(result.summary)
                    .font(.caption)
                    .lineSpacing(3)
                    .padding()
                    .background(Color("InputBackground"))
                    .cornerRadius(8)

                if !result.stackOrder.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Stack (resolves top-down)")
                            .font(.subheadline)
                            .fontWeight(.semibold)
                            .foregroundColor(Color("AccentRed"))
                        ForEach(Array(result.stackOrder.enumerated()), id: \.offset) { i, item in
                            Text("\(i + 1). \(item)")
                                .font(.caption)
                        }
                    }
                    .padding()
                    .background(Color("InputBackground"))
                    .cornerRadius(8)
                }
            }

            // Warnings
            ForEach(result.warnings, id: \.self) { warning in
                HStack {
                    Image(systemName: "exclamationmark.triangle")
                        .foregroundColor(.yellow)
                    Text(warning)
                        .font(.caption)
                }
                .padding()
                .background(Color("InputBackground"))
                .cornerRadius(8)
            }
        }
    }

    // MARK: - Helpers

    private func addPlayer() {
        let name = newPlayerName.trimmingCharacters(in: .whitespaces)
        vm.addPlayer(name: name)
        newPlayerName = ""
    }

    private func permanentBinding(for index: Int) -> Binding<String> {
        Binding(
            get: { permanentInputs[index] ?? "" },
            set: { permanentInputs[index] = $0 }
        )
    }
}

// MARK: - Flow Layout for permanent tags

struct FlowLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let result = arrange(proposal: proposal, subviews: subviews)
        return result.size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let result = arrange(proposal: proposal, subviews: subviews)
        for (index, position) in result.positions.enumerated() {
            subviews[index].place(at: CGPoint(x: bounds.minX + position.x, y: bounds.minY + position.y), proposal: .unspecified)
        }
    }

    private func arrange(proposal: ProposedViewSize, subviews: Subviews) -> (size: CGSize, positions: [CGPoint]) {
        let maxWidth = proposal.width ?? .infinity
        var positions: [CGPoint] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var maxX: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth && x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            positions.append(CGPoint(x: x, y: y))
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
            maxX = max(maxX, x)
        }

        return (CGSize(width: maxX, height: y + rowHeight), positions)
    }
}
