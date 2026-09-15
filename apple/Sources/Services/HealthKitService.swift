import Foundation
#if os(iOS)
import HealthKit

/// Reads the three health metrics JARVIS was asked to know — today's steps,
/// today's active energy, and the latest blood-glucose reading — from HealthKit,
/// and asks for permission once. iOS only; on the Mac this file compiles to
/// nothing.
///
/// Read-only: nothing is ever written back into Health. The values are held
/// here so the app can show them and, later, hand a snapshot to the bridge for
/// JARVIS to answer from.
@MainActor
final class HealthKitService: ObservableObject {
    enum Access: Equatable {
        case unknown          // never asked
        case unavailable      // no HealthKit on this device
        case asked            // permission sheet has been shown
    }

    @Published private(set) var access: Access = .unknown
    /// Today's cumulative step count.
    @Published private(set) var steps: Int?
    /// Today's active energy in kilocalories.
    @Published private(set) var activeEnergy: Double?
    /// The most recent blood-glucose reading, in mg/dL, with when it was taken.
    @Published private(set) var glucose: Double?
    @Published private(set) var glucoseDate: Date?
    @Published private(set) var lastRefresh: Date?
    @Published private(set) var lastError: String?

    private let store = HKHealthStore()

    var isAvailable: Bool { HKHealthStore.isHealthDataAvailable() }

    private var readTypes: Set<HKObjectType> {
        var types = Set<HKObjectType>()
        for id in [HKQuantityTypeIdentifier.stepCount, .activeEnergyBurned, .bloodGlucose] {
            if let type = HKObjectType.quantityType(forIdentifier: id) { types.insert(type) }
        }
        return types
    }

    /// Ask once for read access, then pull the first values. HealthKit never
    /// tells an app whether *read* was granted — a denied type simply returns
    /// no data — so there is no "denied" state to show, only "asked" and then
    /// whatever values come back.
    func requestAuthorization() async {
        guard isAvailable else { access = .unavailable; return }
        do {
            try await store.requestAuthorization(toShare: [], read: readTypes)
            access = .asked
            await refresh()
        } catch {
            lastError = error.localizedDescription
            access = .asked
        }
    }

    /// Re-read all three metrics. Safe to call on every foreground.
    func refresh() async {
        guard isAvailable else { return }
        async let steps = todaySum(.stepCount, unit: .count())
        async let energy = todaySum(.activeEnergyBurned, unit: .kilocalorie())
        async let sugar = latestGlucose()
        let (stepsValue, energyValue, sugarValue) = await (steps, energy, sugar)
        // Assigned even when nil. Steps and energy are *today's* sums, and a
        // day with no samples yet returns nil — keeping the old value there
        // carried yesterday's 11 000 steps past midnight and into JARVIS.
        self.steps = stepsValue.map { Int($0) }
        self.activeEnergy = energyValue
        // Glucose is the latest reading, not today's, so a miss keeps it.
        if let sugarValue {
            self.glucose = sugarValue.value
            self.glucoseDate = sugarValue.date
        }
        self.lastRefresh = Date()
    }

    /// A snapshot for handing to the bridge, or nil while nothing is known.
    var snapshot: JarvisAPIClient.HealthSnapshot? {
        guard steps != nil || activeEnergy != nil || glucose != nil else { return nil }
        return JarvisAPIClient.HealthSnapshot(
            at: Date().timeIntervalSince1970,
            steps: steps,
            active_energy_kcal: activeEnergy.map { Int($0.rounded()) },
            glucose_mgdl: glucose.map { Int($0.rounded()) },
            glucose_at: glucoseDate?.timeIntervalSince1970
        )
    }

    private func todaySum(_ id: HKQuantityTypeIdentifier, unit: HKUnit) async -> Double? {
        guard let type = HKQuantityType.quantityType(forIdentifier: id) else { return nil }
        let start = Calendar.current.startOfDay(for: Date())
        let predicate = HKQuery.predicateForSamples(withStart: start, end: Date(), options: .strictStartDate)
        return await withCheckedContinuation { continuation in
            let query = HKStatisticsQuery(quantityType: type, quantitySamplePredicate: predicate,
                                          options: .cumulativeSum) { _, stats, _ in
                continuation.resume(returning: stats?.sumQuantity()?.doubleValue(for: unit))
            }
            store.execute(query)
        }
    }

    private func latestGlucose() async -> (value: Double, date: Date)? {
        guard let type = HKQuantityType.quantityType(forIdentifier: .bloodGlucose) else { return nil }
        let unit = HKUnit(from: "mg/dL")
        let sort = NSSortDescriptor(key: HKSampleSortIdentifierEndDate, ascending: false)
        return await withCheckedContinuation { continuation in
            let query = HKSampleQuery(sampleType: type, predicate: nil, limit: 1,
                                      sortDescriptors: [sort]) { _, samples, _ in
                guard let sample = samples?.first as? HKQuantitySample else {
                    continuation.resume(returning: nil)
                    return
                }
                continuation.resume(returning: (sample.quantity.doubleValue(for: unit), sample.endDate))
            }
            store.execute(query)
        }
    }
}
#endif
