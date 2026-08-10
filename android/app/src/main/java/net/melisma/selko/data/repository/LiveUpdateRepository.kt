package net.melisma.selko.data.repository

import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.auth.status.SessionStatus
import io.github.jan.supabase.realtime.broadcastFlow
import io.github.jan.supabase.realtime.channel
import io.github.jan.supabase.realtime.realtime
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.jsonObject

data class LiveInvalidation(
    val resource: String,
    val operation: String,
    val entityId: String? = null
)

class LiveUpdateRepository(
    private val supabaseClient: SupabaseClient
) {
    private val _invalidations = MutableSharedFlow<LiveInvalidation>(extraBufferCapacity = 64)
    val invalidations: SharedFlow<LiveInvalidation> = _invalidations.asSharedFlow()

    private var channelJob: Job? = null
    private var currentUserId: String? = null
    private var connectionStatus: String = "disconnected"
    private val scope = CoroutineScope(Dispatchers.IO)

    // Debounce: one in-flight per resource with trailing
    private val debounceJobs = mutableMapOf<String, Job>()
    private val inFlight = mutableSetOf<String>()
    private val trailing = mutableMapOf<String, LiveInvalidation>()
    // Serializes cancel+relaunch bookkeeping so a burst of invalidations
    // cannot interleave launches and let a stale debounce job emit.
    private val debounceMutex = Mutex()

    private val allowedResources = setOf("events", "event_sources", "emails", "integrations")

    fun start(userId: String) {
        if (currentUserId == userId && channelJob != null) return
        stop()
        currentUserId = userId
        connectionStatus = "connecting"

        channelJob = scope.launch {
            // Re-authorize the socket on every session change (sign-in and
            // token refresh). Private channels authorize per-JWT; without
            // this the channel goes deaf ~1h after sign-in.
            launch {
                supabaseClient.auth.sessionStatus.collect { status ->
                    if (status is SessionStatus.Authenticated) {
                        status.session.accessToken?.let { refreshAuth(it) }
                    }
                }
            }

            // Terminal channel states do not self-heal: rejoin with capped
            // exponential backoff. On success the database snapshot is the
            // source of truth; the channel is a hint.
            var rejoinAttempts = 0
            while (channelJob?.isActive == true) {
                try {
                    val topic = "user:${userId.lowercase()}:selko-changes"
                    val channel = supabaseClient.channel(topic) {
                        // private channel
                    }
                    try {
                        val session = supabaseClient.auth.currentSessionOrNull()
                        session?.accessToken?.let {
                            supabaseClient.realtime.setAuth(it)
                        }
                    } catch (_: Exception) { }

                    channel.subscribe()
                    connectionStatus = "subscribed"
                    rejoinAttempts = 0
                    catchUp()
                    launch {
                        try {
                            channel.broadcastFlow<JsonObject>("invalidate").collect { payload ->
                                handleInvalidate(payload)
                            }
                        } catch (_: Exception) { }
                    }
                    return@launch
                } catch (e: Exception) {
                    connectionStatus = "error: ${e.message}"
                    rejoinAttempts += 1
                    val backoffMs = minOf(1000L shl (rejoinAttempts - 1).coerceAtMost(6), 60_000L)
                    delay(backoffMs)
                }
            }
        }
    }

    fun stop() {
        channelJob?.cancel()
        channelJob = null
        currentUserId = null
        connectionStatus = "disconnected"
        debounceJobs.values.forEach { it.cancel() }
        debounceJobs.clear()
        inFlight.clear()
        trailing.clear()
    }

    /** Re-authorize the realtime socket with a (possibly rotated) JWT. */
    suspend fun refreshAuth(token: String) {
        try {
            supabaseClient.realtime.setAuth(token)
        } catch (_: Exception) { }
    }

    /**
     * Force a catch-up refetch for every subscribed resource.
     * Unlike start(), this does not short-circuit when the channel already
     * exists — the database snapshot is the source of truth.
     */
    suspend fun catchUp() {
        for (resource in allowedResources) {
            debounceAndEmit(LiveInvalidation(resource = resource, operation = "CATCHUP"))
        }
    }

    fun handleInvalidate(payload: JsonObject) {
        val inner = (payload["payload"] as? JsonObject) ?: payload
        val resource = inner["resource"]?.jsonPrimitive?.content ?: return
        if (resource !in allowedResources) return
        val op = inner["operation"]?.jsonPrimitive?.content ?: "UPDATE"
        val entityId = inner["entity_id"]?.jsonPrimitive?.content
        val inv = LiveInvalidation(resource = resource, operation = op, entityId = entityId)
        scope.launch { debounceAndEmit(inv) }
    }

    // For testing / manual trigger
    fun emitForTest(inv: LiveInvalidation) {
        scope.launch { debounceAndEmit(inv) }
    }

    private suspend fun debounceAndEmit(inv: LiveInvalidation) {
        val resource = inv.resource
        debounceMutex.withLock {
            if (inFlight.contains(resource)) {
                trailing[resource] = inv
                return
            }
            debounceJobs[resource]?.cancel()
            val job = scope.launch {
                delay(350)
                debounceJobs.remove(resource)
                val latest = trailing.remove(resource) ?: inv
                inFlight.add(resource)
                _invalidations.emit(latest)
                // Release after short delay to allow trailing
                delay(10)
                inFlight.remove(resource)
                trailing.remove(resource)?.let { pending ->
                    debounceAndEmit(pending)
                }
            }
            debounceJobs[resource] = job
        }
    }
}
