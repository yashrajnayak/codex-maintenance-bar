import Combine
import Foundation

@MainActor
final class CodexAwakeModel: ObservableObject {
  let caffeinate: CaffeinateController
  let codexMonitor: CodexProcessMonitor

  @Published private(set) var autoWhileCodexRuns: Bool

  private let autoDefaultsKey = "autoWhileCodexRuns"
  private var cancellables = Set<AnyCancellable>()

  init(
    caffeinate: CaffeinateController = CaffeinateController(),
    codexMonitor: CodexProcessMonitor = CodexProcessMonitor()
  ) {
    self.caffeinate = caffeinate
    self.codexMonitor = codexMonitor

    if UserDefaults.standard.object(forKey: autoDefaultsKey) == nil {
      autoWhileCodexRuns = true
    } else {
      autoWhileCodexRuns = UserDefaults.standard.bool(forKey: autoDefaultsKey)
    }

    self.codexMonitor.onStatusChange = { [weak self] _ in
      Task { @MainActor in
        self?.reconcileAutoState()
      }
    }

    self.caffeinate.objectWillChange
      .sink { [weak self] _ in
        Task { @MainActor in
          self?.objectWillChange.send()
        }
      }
      .store(in: &cancellables)

    self.codexMonitor.objectWillChange
      .sink { [weak self] _ in
        Task { @MainActor in
          self?.objectWillChange.send()
        }
      }
      .store(in: &cancellables)

    reconcileAutoState()
  }

  var statusText: String {
    guard caffeinate.isRunning else {
      return "Awake mode off"
    }

    if let activeSession = caffeinate.activeSession {
      if let activeSource = caffeinate.activeSource {
        return "Keeping Mac awake: \(activeSession.displayName) (\(activeSource.displayName))"
      }
      return "Keeping Mac awake: \(activeSession.displayName)"
    }

    return "Keeping Mac awake"
  }

  var codexStatusText: String {
    codexMonitor.isCodexRunning ? "Codex detected" : "Codex not detected"
  }

  var stopTitle: String {
    caffeinate.activeSource == .codexAuto ? "Stop and Turn Off Auto" : "Stop Keeping Awake"
  }

  func setAutoWhileCodexRuns(_ enabled: Bool) {
    autoWhileCodexRuns = enabled
    UserDefaults.standard.set(enabled, forKey: autoDefaultsKey)
    reconcileAutoState()
  }

  func startManualSession(_ session: AwakeSession) {
    caffeinate.start(session, source: .manual)
  }

  func stopSession() {
    if caffeinate.activeSource == .codexAuto {
      setAutoWhileCodexRuns(false)
    }
    caffeinate.stop()
  }

  func reconcileAutoState() {
    codexMonitor.refresh()

    guard autoWhileCodexRuns else {
      caffeinate.stopAutomaticSession()
      return
    }

    if codexMonitor.isCodexRunning {
      if !caffeinate.isRunning {
        caffeinate.start(.indefinite, source: .codexAuto)
      }
    } else {
      caffeinate.stopAutomaticSession()
    }
  }
}
