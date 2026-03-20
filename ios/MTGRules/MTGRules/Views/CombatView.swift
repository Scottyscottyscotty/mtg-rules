import SwiftUI

struct CombatView: View {
    @StateObject private var vm = CombatViewModel()

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    // Defending player
                    HStack {
                        Text("Defending player:")
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                        TextField("Name", text: $vm.defendingPlayer)
                            .textFieldStyle(.roundedBorder)
                    }

                    // Attackers
                    ForEach(Array(vm.assignments.enumerated()), id: \.offset) { ai, assignment in
                        attackerCard(assignment: assignment, index: ai)
                    }

                    // Add attacker / simulate
                    HStack {
                        Button("+ Attacker") { vm.addAttacker() }
                            .buttonStyle(.bordered)
                            .tint(Color("AccentRed"))

                        Spacer()

                        Button {
                            Task { await vm.simulateCombat() }
                        } label: {
                            Text("Simulate Combat")
                                .fontWeight(.semibold)
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(Color("AccentRed"))
                        .disabled(vm.isLoading || vm.assignments.isEmpty)
                    }

                    // Loading
                    if vm.isLoading {
                        ProgressView("Simulating...")
                            .tint(Color("AccentRed"))
                    }

                    if let error = vm.error {
                        Text(error)
                            .foregroundColor(Color("AccentRed"))
                            .font(.caption)
                    }

                    // Results
                    if let result = vm.result {
                        resultSection(result)
                    }
                }
                .padding()
            }
            .background(Color("Background"))
            .navigationTitle("Combat")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    // MARK: - Attacker Card

    private func attackerCard(assignment: CombatBlockAssignment, index ai: Int) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Attacker \(ai + 1)")
                    .font(.headline)
                    .foregroundColor(Color("AccentRed"))
                Spacer()
                Button("Remove") { vm.removeAttacker(at: ai) }
                    .font(.caption)
                    .foregroundColor(Color("AccentRed"))
            }

            HStack(spacing: 8) {
                TextField("Card name", text: Binding(
                    get: { vm.assignments[ai].attacker.cardName },
                    set: { vm.assignments[ai].attacker.cardName = $0 }
                ))
                .textFieldStyle(.roundedBorder)

                TextField("P", value: Binding(
                    get: { vm.assignments[ai].attacker.power },
                    set: { vm.assignments[ai].attacker.power = $0 }
                ), format: .number)
                .textFieldStyle(.roundedBorder)
                .frame(width: 44)

                Text("/").foregroundColor(.secondary)

                TextField("T", value: Binding(
                    get: { vm.assignments[ai].attacker.toughness },
                    set: { vm.assignments[ai].attacker.toughness = $0 }
                ), format: .number)
                .textFieldStyle(.roundedBorder)
                .frame(width: 44)
            }

            // Blockers
            if !assignment.blockers.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Blockers:")
                        .font(.caption)
                        .foregroundColor(.secondary)

                    ForEach(Array(assignment.blockers.enumerated()), id: \.offset) { bi, blocker in
                        HStack(spacing: 6) {
                            TextField("Blocker", text: Binding(
                                get: { vm.assignments[ai].blockers[bi].cardName },
                                set: { vm.assignments[ai].blockers[bi].cardName = $0 }
                            ))
                            .textFieldStyle(.roundedBorder)
                            .font(.caption)

                            TextField("P", value: Binding(
                                get: { vm.assignments[ai].blockers[bi].power },
                                set: { vm.assignments[ai].blockers[bi].power = $0 }
                            ), format: .number)
                            .textFieldStyle(.roundedBorder)
                            .frame(width: 38)
                            .font(.caption)

                            TextField("T", value: Binding(
                                get: { vm.assignments[ai].blockers[bi].toughness },
                                set: { vm.assignments[ai].blockers[bi].toughness = $0 }
                            ), format: .number)
                            .textFieldStyle(.roundedBorder)
                            .frame(width: 38)
                            .font(.caption)

                            Button { vm.removeBlocker(from: ai, at: bi) } label: {
                                Image(systemName: "xmark.circle.fill")
                                    .font(.caption2)
                            }
                        }
                    }
                }
                .padding(.leading, 12)
            }

            Button("+ Blocker") { vm.addBlocker(to: ai) }
                .font(.caption)
                .padding(.leading, 12)
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

    private func resultSection(_ result: CombatSimResult) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            // Player damage
            if !result.playerDamage.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array(result.playerDamage.keys.sorted()), id: \.self) { player in
                        Text("\(player) takes \(result.playerDamage[player]!) damage")
                            .font(.subheadline)
                            .fontWeight(.semibold)
                    }
                }
                .padding()
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color("InputBackground"))
                .cornerRadius(8)
            }

            // Life gained
            if !result.lifeGained.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array(result.lifeGained.keys.sorted()), id: \.self) { player in
                        Text("\(player) gains \(result.lifeGained[player]!) life (lifelink)")
                            .font(.subheadline)
                            .foregroundColor(.green)
                    }
                }
                .padding()
                .background(Color("InputBackground"))
                .cornerRadius(8)
            }

            // Deaths
            if !result.creaturesThatDie.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Creatures That Die")
                        .font(.subheadline)
                        .fontWeight(.semibold)
                        .foregroundColor(Color("AccentRed"))
                    ForEach(result.creaturesThatDie, id: \.self) { name in
                        Text("  \(name)")
                            .font(.caption)
                    }
                }
                .padding()
                .background(Color("InputBackground"))
                .cornerRadius(8)
            }

            // Notes
            if !result.notes.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Step-by-Step")
                        .font(.subheadline)
                        .fontWeight(.semibold)
                    ForEach(Array(result.notes.enumerated()), id: \.offset) { _, note in
                        Text(note)
                            .font(.caption)
                            .foregroundColor(note.hasPrefix("  *") ? .orange : .secondary)
                    }
                }
                .padding()
                .background(Color("InputBackground"))
                .cornerRadius(8)
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
}
