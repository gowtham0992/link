import Foundation

/// Bridge to the `lnk` CLI. The CLI's `--json` output is LinkBar's entire
/// backend: no server, no sockets, no new API surface — the same reviewed
/// commands every other Link surface uses.
/// Thread-safe holder for the stderr bytes read on a background queue.
final class DataBox: @unchecked Sendable {
    private let lock = NSLock()
    private var data = Data()
    func set(_ value: Data) { lock.lock(); data = value; lock.unlock() }
    func get() -> Data { lock.lock(); defer { lock.unlock() }; return data }
}

enum LinkCLI {
    struct CLIError: Error, CustomStringConvertible {
        let message: String
        var description: String { message }
    }

    /// Workspace the app operates on. Order: LINK_WORKSPACE (a launch-time
    /// override, also what the snapshot harness uses), the workspace chosen
    /// in Settings, then ~/link - the CLI's own pathless fallback. An app
    /// launched from Finder or at login never sees shell exports, so the
    /// Settings choice is the one that works for most people.
    static let workspaceDefaultsKey = "LinkWorkspace"

    static var workspace: String {
        if let env = workspaceFromEnvironment { return env }
        if let chosen = UserDefaults.standard.string(forKey: workspaceDefaultsKey), !chosen.isEmpty {
            return (chosen as NSString).expandingTildeInPath
        }
        return defaultWorkspace
    }

    static var workspaceFromEnvironment: String? {
        guard let env = ProcessInfo.processInfo.environment["LINK_WORKSPACE"], !env.isEmpty else { return nil }
        return (env as NSString).expandingTildeInPath
    }

    static var defaultWorkspace: String {
        (NSHomeDirectory() as NSString).appendingPathComponent("link")
    }

    /// True when Settings, not the default, decides the workspace.
    static var workspaceIsCustom: Bool {
        !(UserDefaults.standard.string(forKey: workspaceDefaultsKey) ?? "").isEmpty
    }

    static func setWorkspace(_ path: String?) {
        if let path, !path.isEmpty {
            UserDefaults.standard.set(path, forKey: workspaceDefaultsKey)
        } else {
            UserDefaults.standard.removeObject(forKey: workspaceDefaultsKey)
        }
    }

    /// "~/link" instead of "/Users/you/link" wherever a path is shown.
    static func abbreviated(_ path: String) -> String {
        (path as NSString).abbreviatingWithTildeInPath
    }

    /// Locate the lnk launcher. Order: LINK_CLI env, the places installs
    /// land (Homebrew, pipx, Link's own venv), then PATH. A GUI app inherits
    /// a minimal PATH - /usr/bin:/bin - so `which` alone misses every
    /// user-level install; the usual bin directories are added first.
    static func lnkPath() -> String? {
        if let env = ProcessInfo.processInfo.environment["LINK_CLI"], !env.isEmpty {
            return env
        }
        let home = NSHomeDirectory()
        let userBins = [
            "/opt/homebrew/bin", "/usr/local/bin",
            (home as NSString).appendingPathComponent(".local/bin"),
            (home as NSString).appendingPathComponent(".link-mcp-venv/bin"),
        ]
        for dir in userBins {
            let candidate = (dir as NSString).appendingPathComponent("lnk")
            if FileManager.default.isExecutableFile(atPath: candidate) { return candidate }
        }
        let which = Process()
        which.executableURL = URL(fileURLWithPath: "/usr/bin/which")
        which.arguments = ["lnk"]
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = (userBins + [environment["PATH"] ?? "/usr/bin:/bin"]).joined(separator: ":")
        which.environment = environment
        let pipe = Pipe()
        which.standardOutput = pipe
        which.standardError = Pipe()
        try? which.run()
        which.waitUntilExit()
        let out = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return out.isEmpty ? nil : out
    }

    /// Run `lnk <args>` and return stdout. Blocking — call off the main actor.
    static func run(_ args: [String]) throws -> Data {
        guard let lnk = lnkPath() else {
            throw CLIError(message: "lnk not found — install Link (brew install gowtham0992/link/link) or set LINK_CLI")
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: lnk)
        process.arguments = args
        let (data, errData) = try drain(process)
        if process.terminationStatus != 0 && data.isEmpty {
            let message = String(data: errData, encoding: .utf8) ?? "lnk exited \(process.terminationStatus)"
            throw CLIError(message: message.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        return data
    }

    /// Run an arbitrary executable + args (not the `lnk` launcher) — used for
    /// the exact remediation commands `verify-mcp` emits (e.g. a venv pip
    /// upgrade). Blocking; call off the main actor.
    @discardableResult
    static func runRaw(_ command: [String]) throws -> Data {
        guard let executable = command.first else {
            throw CLIError(message: "empty command")
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = Array(command.dropFirst())
        let (data, errData) = try drain(process)
        if process.terminationStatus != 0 {
            let message = String(data: errData, encoding: .utf8) ?? ""
            throw CLIError(message: lastLine(message) ?? "\(executable) exited \(process.terminationStatus)")
        }
        return data
    }

    /// Start `process` and read stdout and stderr at the same time.
    ///
    /// Reading one pipe to EOF and then the other deadlocks as soon as the
    /// child writes more than a pipe buffer (64 KB) to the second one: the
    /// child blocks writing stderr, never closes stdout, and the read never
    /// returns. Python tracebacks from a broken venv and pip or model
    /// download progress are all that size.
    private static func drain(_ process: Process) throws -> (Data, Data) {
        let stdout = Pipe()
        let stderr = Pipe()
        process.standardOutput = stdout
        process.standardError = stderr
        try process.run()
        let errBox = DataBox()
        let group = DispatchGroup()
        group.enter()
        DispatchQueue.global(qos: .utility).async {
            errBox.set(stderr.fileHandleForReading.readDataToEndOfFile())
            group.leave()
        }
        let data = stdout.fileHandleForReading.readDataToEndOfFile()
        group.wait()
        process.waitUntilExit()
        return (data, errBox.get())
    }

    /// The last non-empty line of CLI stderr: the part a person can act on.
    static func lastLine(_ text: String) -> String? {
        text.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }
            .last { !$0.isEmpty }
    }

    /// Why the CLI cannot serve this workspace, in words a person can act on.
    static func diagnose(_ workspace: String) -> String {
        guard lnkPath() != nil else {
            return "lnk not found - install Link (brew install gowtham0992/link/link) or set LINK_CLI."
        }
        let wiki = (workspace as NSString).appendingPathComponent("wiki")
        if !FileManager.default.fileExists(atPath: wiki) {
            return "No Link workspace at \(abbreviated(workspace)) - run lnk setup, or choose one in Settings."
        }
        do {
            _ = try run(["status", workspace, "--json"])
            return "lnk answered, but its inbox reads failed - try Refresh, or run lnk doctor."
        } catch {
            return "lnk failed: " + (lastLine(String(describing: error)) ?? "unknown error")
        }
    }

    /// Fire-and-forget for long-lived processes (the local viewer).
    static func launchDetached(_ args: [String]) {
        guard let lnk = lnkPath() else { return }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: lnk)
        process.arguments = args
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try? process.run()
    }

    static func runJSON<T: Decodable>(_ type: T.Type, _ args: [String]) throws -> T {
        let data = try run(args)
        return try JSONDecoder().decode(type, from: data)
    }
}
