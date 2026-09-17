import AppKit
import UserNotifications

/// Native notifications when a session capture lands, with an Accept action
/// on the banner — the review gate meeting you the moment memory is proposed.
///
/// The open question is whether macOS grants notification authorization to an
/// ad-hoc-signed (unsigned) app; UNUserNotificationCenter ties permission to
/// the code signature. `probeAuthorization` answers that on the real machine
/// so we know whether this feature is free or needs the $99 signed build.
@MainActor
final class NotificationManager: NSObject, @preconcurrency UNUserNotificationCenterDelegate {
    static let shared = NotificationManager()

    private let acceptAction = "LINK_ACCEPT"
    private let reviewAction = "LINK_REVIEW"
    private let captureCategory = "LINK_CAPTURE"
    private weak var store: LinkStore?
    /// Capture paths already announced, so a refresh burst never double-notifies.
    private var announced: Set<String> = []
    private var primed = false
    /// macOS grants notification authorization only to properly signed apps;
    /// an ad-hoc/unsigned build is denied outright. When false, the whole
    /// feature stays dormant (no dead API calls) and lights up automatically
    /// once LinkBar ships signed + notarized.
    private var authorized = false

    func install(store: LinkStore) {
        self.store = store
        let center = UNUserNotificationCenter.current()
        center.delegate = self

        let accept = UNNotificationAction(identifier: acceptAction, title: "Accept", options: [])
        let review = UNNotificationAction(identifier: reviewAction, title: "Review…", options: [.foreground])
        let category = UNNotificationCategory(identifier: captureCategory,
                                              actions: [accept, review],
                                              intentIdentifiers: [],
                                              options: [])
        center.setNotificationCategories([category])
        center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
            Task { @MainActor in self.authorized = granted }
        }
    }

    /// Seed `announced` with whatever is already in the inbox so the first
    /// refresh after launch doesn't fire a banner for every old capture.
    func prime(with captures: [CaptureItem]) {
        guard !primed else { return }
        announced.formUnion(captures.map(\.path))
        primed = true
    }

    /// A workspace switch means a different inbox: forget what was announced
    /// so the first refresh seeds again instead of firing a banner per file.
    func reprime() {
        primed = false
        announced = []
    }

    /// Called on each refresh with the current inbox; notifies once per new
    /// capture path.
    func announceNewCaptures(_ captures: [CaptureItem]) {
        guard authorized else { return }   // inert on unsigned builds
        guard primed else { prime(with: captures); return }
        for capture in captures where !announced.contains(capture.path) {
            announced.insert(capture.path)
            post(for: capture)
        }
    }

    /// The digest that delivers itself: once a week, when the digest has
    /// something to say, one banner says it — "4 new · 2 aging · 1 saying
    /// the same thing twice". A quiet week posts nothing; a reflection
    /// ritual that requires discipline is not a ritual.
    private let digestStampKey = "LinkBarLastDigestNotice"

    func announceWeeklyDigest(_ digest: DigestPayload) {
        guard authorized else { return }
        let last = UserDefaults.standard.double(forKey: digestStampKey)
        guard Date().timeIntervalSince1970 - last > 6.5 * 86_400 else { return }
        var parts: [String] = []
        if digest.learnedCount > 0 { parts.append("\(digest.learnedCount) new") }
        if digest.overdueCount > 0 { parts.append("\(digest.overdueCount) aging") }
        if digest.driftingCount > 0 { parts.append("\(digest.driftingCount) saying the same thing twice") }
        if let never = digest.usage?.neverRetrievedCount, never > 0 {
            parts.append("\(never) never used")
        }
        guard !parts.isEmpty else { return }
        UserDefaults.standard.set(Date().timeIntervalSince1970, forKey: digestStampKey)

        let content = UNMutableNotificationContent()
        content.title = "Your week with Link"
        content.body = parts.joined(separator: " · ")
        content.sound = nil
        UNUserNotificationCenter.current().add(
            UNNotificationRequest(identifier: "link-weekly-digest", content: content, trigger: nil)
        )
    }

    private func post(for capture: CaptureItem) {
        let content = UNMutableNotificationContent()
        content.title = "Link captured a memory"
        if let first = capture.proposals?.first, let memory = first.memory {
            content.subtitle = capture.displayTitle
            content.body = "Will save: \(memory)"
        } else {
            content.body = capture.displayTitle
        }
        content.categoryIdentifier = captureCategory
        content.userInfo = ["path": capture.path]
        content.sound = nil

        let request = UNNotificationRequest(identifier: capture.path, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }

    // Banner actions

    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        let path = response.notification.request.content.userInfo["path"] as? String
        switch response.actionIdentifier {
        case acceptAction:
            if let path { Task { @MainActor in self.store?.acceptCaptureByPath(path) } }
        case reviewAction, UNNotificationDefaultActionIdentifier:
            NSApp.activate(ignoringOtherApps: true)
            PaletteController.shared.hide()
        default:
            break
        }
        completionHandler()
    }

    // Show banners even while LinkBar is frontmost (it's a menu-bar agent).
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .list])
    }

    /// Report the current authorization status — the ad-hoc-signing answer.
    /// Invoked by `LINKBAR_NOTIFY_TEST=1` on the installed bundle.
    func probeAuthorization(_ done: @escaping (String) -> Void) {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { granted, error in
            UNUserNotificationCenter.current().getNotificationSettings { settings in
                let status: String
                switch settings.authorizationStatus {
                case .authorized: status = "authorized"
                case .denied: status = "denied"
                case .notDetermined: status = "notDetermined"
                case .provisional: status = "provisional"
                case .ephemeral: status = "ephemeral"
                @unknown default: status = "unknown"
                }
                let err = error.map { " error=\($0.localizedDescription)" } ?? ""
                done("granted=\(granted) status=\(status)\(err)")
            }
        }
    }
}
