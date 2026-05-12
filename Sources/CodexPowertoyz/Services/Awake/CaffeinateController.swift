import AppKit
import Foundation

enum AwakeSource: String, Sendable {
  case manual
  case codexAuto

  var displayName: String {
    switch self {
    case .manual:
      return "Manual"
    case .codexAuto:
      return "Codex auto"
    }
  }
}

@MainActor
final class CaffeinateController: ObservableObject {
  @Published private(set) var isRunning = false
  @Published private(set) var activeSession: AwakeSession?
  @Published private(set) var activeSource: AwakeSource?
  @Published private(set) var lastError: String?

  private var process: Process?
  private var terminationObserver: NSObjectProtocol?

  init() {
    terminationObserver = NotificationCenter.default.addObserver(
      forName: NSApplication.willTerminateNotification,
      object: nil,
      queue: .main
    ) { [weak self] _ in
      Task { @MainActor in
        self?.stop()
      }
    }
  }

  deinit {
    process?.terminate()
  }

  func start(_ session: AwakeSession = .indefinite, source: AwakeSource = .manual) {
    stop()

    let command = CaffeinateCommand(duration: session.duration)
    let process = Process()
    process.executableURL = URL(fileURLWithPath: command.executablePath)
    process.arguments = command.arguments

    process.terminationHandler = { [weak self] _ in
      Task { @MainActor in
        guard self?.process === process else {
          return
        }
        self?.process = nil
        self?.isRunning = false
        self?.activeSession = nil
        self?.activeSource = nil
      }
    }

    do {
      try process.run()
      self.process = process
      isRunning = true
      activeSession = session
      activeSource = source
      lastError = nil
    } catch {
      self.process = nil
      isRunning = false
      activeSession = nil
      activeSource = nil
      lastError = error.localizedDescription
    }
  }

  func stop() {
    guard let process else {
      isRunning = false
      activeSession = nil
      activeSource = nil
      return
    }

    process.terminate()
    self.process = nil
    isRunning = false
    activeSession = nil
    activeSource = nil
  }

  func stopAutomaticSession() {
    guard activeSource == .codexAuto else {
      return
    }
    stop()
  }
}
