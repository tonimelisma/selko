import Foundation
import Supabase
import Combine

/// Invalidation hint from private Broadcast (never authoritative data)
struct LiveInvalidation: Equatable, Sendable {
    let resource: String
    let operation: String
    let entityId: UUID?
    let occurredAt: Date
}

/// Coordinator: one private channel per signed-in user/process, per spec
@MainActor
final class LiveUpdateService: ObservableObject {
    @Published private(set) var connectionStatus: String = "disconnected"

    private var channel: RealtimeChannelV2?
    private var userId: UUID?
    private let supabase: SupabaseClient
    private var debounceTasks: [String: Task<Void, Never>] = [:]
    private var inFlight: Set<String> = []
    private var trailing: [String: LiveInvalidation] = [:]

    private let subject = PassthroughSubject<LiveInvalidation, Never>()
    var publisher: AnyPublisher<LiveInvalidation, Never> { subject.eraseToAnyPublisher() }
    var stream: AsyncStream<LiveInvalidation> {
        AsyncStream { continuation in
            let cancellable = subject.sink { inv in
                continuation.yield(inv)
            }
            continuation.onTermination = { _ in cancellable.cancel() }
        }
    }

    init(supabase: SupabaseClient) {
        self.supabase = supabase
    }

    func start(userId: UUID) async {
        if self.userId == userId && channel != nil { return }
        await stop()
        self.userId = userId
        connectionStatus = "connecting"
        // setAuth for private channel
        do {
            let session = try await supabase.auth.session
            await supabase.realtimeV2.setAuth(session.accessToken)
        } catch {
            // Non-fatal: snapshot fetching still works
            print("[LiveUpdate] setAuth failed: \(error)")
        }
        let topic = "user:\(userId.uuidString.lowercased()):selko-changes"
        let ch = supabase.channel(topic) { config in
            config.isPrivate = true
        }
        ch.onBroadcast(event: "invalidate") { [weak self] message in
            guard let self else { return }
            Task { @MainActor in
                self.handleInvalidate(message)
            }
        }
        self.channel = ch
        // Terminal channel states (auth expiry, server drop) do not self-heal.
        // Rejoin with capped exponential backoff; on success the database
        // snapshot is the source of truth, the channel is a hint.
        var rejoinAttempts = 0
        while !Task.isCancelled {
            do {
                try await ch.subscribeWithError()
                rejoinAttempts = 0
                connectionStatus = "subscribed"
                // Synthetic refresh on SUBSCRIBED per reliability model
                await catchUp()
                return
            } catch {
                connectionStatus = "error: \(error.localizedDescription)"
                rejoinAttempts += 1
                let delay = min(1.0 * pow(2.0, Double(rejoinAttempts - 1)), 60.0)
                try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            }
        }
    }

    /// Re-authorize the realtime socket after a token rotation.
    /// Private channels authorize per-JWT; without this the channel goes deaf
    /// when the access token expires (~1h) and nothing reports it.
    func refreshAuth(_ token: String) async {
        await supabase.realtimeV2.setAuth(token)
    }

    func stop() async {
        if let ch = channel {
            await supabase.realtimeV2.removeChannel(ch)
            channel = nil
        }
        userId = nil
        connectionStatus = "disconnected"
        for t in debounceTasks.values { t.cancel() }
        debounceTasks.removeAll()
        trailing.removeAll()
        inFlight.removeAll()
    }

    func handleInvalidate(_ message: JSONObject) {
        // Realtime V2 payload is {payload: {resource, operation, entity_id, occurred_at}, event: "invalidate"}
        let payload = (message["payload"] as? JSONObject) ?? message
        guard let resource = payload["resource"] as? String,
              Set(["events", "event_sources", "emails", "integrations"]).contains(resource) else { return }
        let op = payload["operation"] as? String ?? "UPDATE"
        let eidStr = payload["entity_id"] as? String
        let eid = eidStr.flatMap { UUID(uuidString: $0) }
        let inv = LiveInvalidation(resource: resource, operation: op, entityId: eid, occurredAt: Date())
        Task { await debounceAndEmit(inv) }
    }

    private func debounceAndEmit(_ inv: LiveInvalidation) async {
        let resource = inv.resource
        if inFlight.contains(resource) {
            trailing[resource] = inv
            return
        }
        debounceTasks[resource]?.cancel()
        let task = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 350_000_000)
            guard let self, !Task.isCancelled else { return }
            self.debounceTasks.removeValue(forKey: resource)
            let latest = self.trailing.removeValue(forKey: resource) ?? inv
            self.inFlight.insert(resource)
            self.subject.send(latest)
            // Release after handler's fetch (consumers are async); next tick allows trailing
            Task { @MainActor in
                try? await Task.sleep(nanoseconds: 10_000_000)
                self.inFlight.remove(resource)
                if let pending = self.trailing.removeValue(forKey: resource) {
                    await self.debounceAndEmit(pending)
                }
            }
        }
        debounceTasks[resource] = task
    }

    // For scenePhase catch-up: a synthetic invalidation for every subscribed
    // resource. Unlike start(), this does not short-circuit when the channel
    // already exists — the database snapshot is the source of truth.
    func catchUp() async {
        for resource in ["events", "event_sources", "integrations", "emails"] {
            await debounceAndEmit(LiveInvalidation(resource: resource, operation: "CATCHUP", entityId: nil, occurredAt: Date()))
        }
    }
}
