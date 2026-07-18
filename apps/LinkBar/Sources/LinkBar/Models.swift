import Foundation

/// Decodable views over `lnk ... --json` payloads. Tolerant on purpose:
/// only the fields the popover renders are required.

struct MemoryInbox: Decodable {
    let reviewCount: Int
    let items: [InboxItem]

    enum CodingKeys: String, CodingKey {
        case reviewCount = "review_count"
        case items
    }
}

struct InboxItem: Decodable, Identifiable {
    let name: String
    let title: String
    let memoryType: String
    let tldr: String?
    let highestSeverity: String?

    var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name, title, tldr
        case memoryType = "memory_type"
        case highestSeverity = "highest_severity"
    }
}

struct CaptureInbox: Decodable {
    let count: Int
    let captures: [CaptureItem]
}

struct ProposalPreview: Decodable {
    let title: String?
    let memory: String?
    let memoryType: String?

    enum CodingKeys: String, CodingKey {
        case title, memory
        case memoryType = "memory_type"
    }
}

struct CaptureItem: Decodable, Identifiable {
    let path: String
    let title: String?
    let project: String?
    let proposals: [ProposalPreview]?
    let snippet: String?
    let decisionTrail: [String]?
    let minedFromUserTurns: Bool?

    enum CodingKeys: String, CodingKey {
        case path, title, project, proposals, snippet
        case decisionTrail = "decision_trail"
        case minedFromUserTurns = "mined_from_user_turns"
    }

    var id: String { path }
    var displayTitle: String {
        title ?? (path as NSString).lastPathComponent
    }

    /// Capture filenames start with a UTC stamp (20260712T165329Z-…);
    /// shown as local relative time ("2h ago") so same-titled sessions
    /// disambiguate without the reader doing timezone math.
    var capturedAt: String? {
        let name = (path as NSString).lastPathComponent
        guard name.count >= 16, name.prefix(8).allSatisfy(\.isNumber) else { return nil }
        var comps = DateComponents()
        comps.year = Int(name.prefix(4)); comps.month = Int(name.dropFirst(4).prefix(2))
        comps.day = Int(name.dropFirst(6).prefix(2)); comps.hour = Int(name.dropFirst(9).prefix(2))
        comps.minute = Int(name.dropFirst(11).prefix(2)); comps.second = Int(name.dropFirst(13).prefix(2))
        comps.timeZone = TimeZone(identifier: "UTC")
        guard let date = Calendar(identifier: .gregorian).date(from: comps) else { return nil }
        return date.relativeLabel
    }
}

extension Date {
    /// Parse Link's UTC stamps ("2026-07-12T18:00:00Z").
    static func fromLinkStamp(_ stamp: String) -> Date? {
        ISO8601DateFormatter().date(from: stamp)
    }

    /// "2h ago" under a day, "Jul 12" beyond — compact enough for a row.
    var relativeLabel: String {
        let interval = Date().timeIntervalSince(self)
        if interval < 90 { return "now" }
        if interval < 3600 { return "\(Int(interval / 60))m ago" }
        if interval < 86_400 { return "\(Int(interval / 3600))h ago" }
        if interval < 7 * 86_400 { return "\(Int(interval / 86_400))d ago" }
        let formatter = DateFormatter()
        formatter.dateFormat = "MMM d"
        return formatter.string(from: self)
    }
}

struct MemoryLog: Decodable {
    let entries: [LogEntry]
}

struct LogEntry: Decodable, Identifiable {
    let timestamp: String
    let operation: String
    let description: String?

    // timestamp+operation alone collides when one command writes twice
    // in a second (ForEach then drops rows) — include the description.
    var id: String { timestamp + operation + (description ?? "") }

    var date: Date? { Date.fromLinkStamp(timestamp) }
}

struct RecallPayload: Decodable {
    let memories: [RecalledMemory]
    let abstention: Abstention?
}

struct Abstention: Decodable {
    let recommended: Bool
    let reason: String?
}

struct RecalledMemory: Decodable, Identifiable {
    let name: String
    let title: String
    let memoryType: String?
    let confidence: String?
    let tldr: String?

    var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name, title, confidence, tldr
        case memoryType = "memory_type"
    }
}

struct StatusPayload: Decodable {
    struct Warning: Decodable {
        let code: String?
        let message: String?
    }

    let version: String?
    let warnings: [Warning]?
    let memoryCount: Int?
    let activeMemoryCount: Int?
    let needsReviewCount: Int?
    let contentPageCount: Int?

    enum CodingKeys: String, CodingKey {
        case version, warnings
        case memoryCount = "memory_count"
        case activeMemoryCount = "active_memory_count"
        case needsReviewCount = "needs_review_count"
        case contentPageCount = "content_page_count"
    }
}

struct RememberResult: Decodable {
    let created: Bool
    let secret: Bool?
    let message: String?
}

// MARK: - Status dashboard payloads

/// `lnk verify-mcp --json`: is the MCP server reachable and version-matched?
struct MCPVerify: Decodable {
    struct Component: Decodable {
        let installed: Bool?
        let version: String?
        let mcpSdk: Bool?
        let error: String?
        enum CodingKeys: String, CodingKey {
            case installed, version, error
            case mcpSdk = "mcp_sdk"
        }
    }
    struct Action: Decodable {
        let label: String?
        let commandText: String?
        let command: [String]?
        enum CodingKeys: String, CodingKey {
            case label, command
            case commandText = "command_text"
        }
    }

    let ready: Bool
    let python: String?
    let expectedVersion: String?
    let versionMatches: Bool?
    let linkMcp: Component?
    let nextActions: [Action]?

    enum CodingKeys: String, CodingKey {
        case ready, python
        case expectedVersion = "expected_version"
        case versionMatches = "version_matches"
        case linkMcp = "link_mcp"
        case nextActions = "next_actions"
    }
}

/// `lnk semantic --json`: which recall power is active (lexical/fast/quality + rerank).
struct SemanticStatus: Decodable {
    let enabled: Bool
    let tier: String?
    let provider: String?
    let mode: String?
    let model: String?
    let rerankReady: Bool?
    let rerankState: String?
    let modelAvailableOffline: Bool?
    let indexedMemories: Int?
    let memoryCount: Int?

    enum CodingKeys: String, CodingKey {
        case enabled, tier, provider, mode, model
        case rerankReady = "rerank_ready"
        case rerankState = "rerank_state"
        case modelAvailableOffline = "model_available_offline"
        case indexedMemories = "indexed_memories"
        case memoryCount = "memory_count"
    }
}

/// One row in the Status dashboard: a Link surface and its live health.
struct SurfaceHealth: Identifiable {
    enum Level {
        case ok, warn, error, info
        var color: (r: Double, g: Double, b: Double) {
            switch self {
            case .ok:    return (0.30, 0.72, 0.42)   // green
            case .warn:  return (0.90, 0.62, 0.20)   // amber
            case .error: return (0.86, 0.30, 0.24)   // red
            case .info:  return (0.55, 0.55, 0.55)   // neutral
            }
        }
    }
    /// A one-click remediation for an unhealthy surface.
    struct Fix {
        let label: String
        let action: () -> Void
    }

    let icon: String
    let name: String
    let level: Level
    let detail: String
    var fix: Fix? = nil

    var id: String { name }
}

/// A live agent session detected from transcript activity — the "pulse".
struct AgentSession: Identifiable {
    let project: String
    let lastActive: Date

    var id: String { project }
    var minutesAgo: Int { max(0, Int(Date().timeIntervalSince(lastActive) / 60)) }
}
