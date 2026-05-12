import AppKit
import Foundation

@MainActor
final class CodexProcessMonitor: ObservableObject {
  @Published private(set) var isCodexRunning = false
  var onStatusChange: ((Bool) -> Void)?

  private let refreshInterval: TimeInterval
  private var refreshTask: Task<Void, Never>?

  init(refreshInterval: TimeInterval = 5) {
    self.refreshInterval = refreshInterval
    refresh()

    let sleepNanoseconds = UInt64(refreshInterval * 1_000_000_000)
    refreshTask = Task { @MainActor [weak self] in
      while !Task.isCancelled {
        try? await Task.sleep(nanoseconds: sleepNanoseconds)
        self?.refresh()
      }
    }
  }

  deinit {
    refreshTask?.cancel()
  }

  func refresh() {
    let detected = Self.detectCodex()
    guard detected != isCodexRunning else {
      return
    }

    isCodexRunning = detected
    onStatusChange?(detected)
  }

  private static func detectCodex() -> Bool {
    if !NSRunningApplication.runningApplications(withBundleIdentifier: "com.openai.codex").isEmpty {
      return true
    }

    return NSWorkspace.shared.runningApplications.contains { app in
      if app.bundleIdentifier == "com.openai.codex" {
        return true
      }

      if app.localizedName == "Codex" {
        return true
      }

      return app.bundleURL?.lastPathComponent == "Codex.app"
    }
  }
}
