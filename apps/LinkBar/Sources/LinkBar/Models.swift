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
    /// showing it disambiguates same-titled sessions.
    var capturedAt: String? {
        let name = (path as NSString).lastPathComponent
        guard name.count >= 16, name.prefix(8).allSatisfy(\.isNumber) else { return nil }
        let month = Int(name.dropFirst(4).prefix(2)) ?? 0
        let day = name.dropFirst(6).prefix(2)
        let hour = name.dropFirst(9).prefix(2)
        let minute = name.dropFirst(11).prefix(2)
        let months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        guard (1...12).contains(month) else { return nil }
        return "\(day) \(months[month]) \(hour):\(minute) UTC"
    }
}

struct MemoryLog: Decodable {
    let entries: [LogEntry]
}

struct LogEntry: Decodable, Identifiable {
    let timestamp: String
    let operation: String
    let description: String?

    var id: String { timestamp + operation }
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
}

struct RememberResult: Decodable {
    let created: Bool
    let secret: Bool?
    let message: String?
}
