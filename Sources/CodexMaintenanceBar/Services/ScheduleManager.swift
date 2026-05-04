import AppKit
import Foundation

@MainActor
final class ScheduleManager: ObservableObject {
  @Published private(set) var isEnabled = false
  @Published private(set) var statusText = "Weekly cleanup off"

  private let fileManager = FileManager.default
  private let label = "io.github.yashrajnayak.codex-maintenance.weekly"

  init() {
    refresh()
    if isEnabled {
      try? installScriptCopy()
    }
  }

  func refresh() {
    isEnabled = fileManager.fileExists(atPath: plistURL.path)
    statusText = isEnabled ? "Weekly cleanup on" : "Weekly cleanup off"
  }

  func enableWeeklyCleanup() {
    do {
      try installScriptCopy()
      try writeLaunchAgent()
      try? runLaunchctl(["bootout", launchDomain, plistURL.path], allowFailure: true)
      try runLaunchctl(["bootstrap", launchDomain, plistURL.path])
      try runLaunchctl(["enable", "\(launchDomain)/\(label)"])
      refresh()
      statusText = "Weekly cleanup on"
    } catch {
      refresh()
      statusText = "Schedule failed"
      NSAlert(error: error).runModal()
    }
  }

  func disableWeeklyCleanup() {
    do {
      try? runLaunchctl(["bootout", launchDomain, plistURL.path], allowFailure: true)
      if fileManager.fileExists(atPath: plistURL.path) {
        try fileManager.removeItem(at: plistURL)
      }
      refresh()
      statusText = "Weekly cleanup off"
    } catch {
      refresh()
      statusText = "Disable failed"
      NSAlert(error: error).runModal()
    }
  }

  func openScheduleFolder() {
    do {
      try fileManager.createDirectory(at: supportDirectory, withIntermediateDirectories: true)
      NSWorkspace.shared.open(supportDirectory)
    } catch {
      NSSound.beep()
    }
  }

  private var launchDomain: String {
    "gui/\(getuid())"
  }

  private var launchAgentsDirectory: URL {
    fileManager.homeDirectoryForCurrentUser
      .appendingPathComponent("Library/LaunchAgents")
  }

  private var supportDirectory: URL {
    fileManager.homeDirectoryForCurrentUser
      .appendingPathComponent("Library/Application Support/CodexMaintenanceBar")
  }

  private var plistURL: URL {
    launchAgentsDirectory.appendingPathComponent("\(label).plist")
  }

  private var scheduledScriptURL: URL {
    supportDirectory.appendingPathComponent("codex_weekly_maintenance.py")
  }

  private var stdoutURL: URL {
    supportDirectory.appendingPathComponent("weekly-cleanup.out.log")
  }

  private var stderrURL: URL {
    supportDirectory.appendingPathComponent("weekly-cleanup.err.log")
  }

  private func installScriptCopy() throws {
    guard let source = resolveScriptURL() else {
      throw ScheduleError.missingScript
    }

    try fileManager.createDirectory(at: supportDirectory, withIntermediateDirectories: true)
    if fileManager.fileExists(atPath: scheduledScriptURL.path) {
      try fileManager.removeItem(at: scheduledScriptURL)
    }
    try fileManager.copyItem(at: source, to: scheduledScriptURL)
    try fileManager.setAttributes([.posixPermissions: 0o755], ofItemAtPath: scheduledScriptURL.path)
  }

  private func writeLaunchAgent() throws {
    try fileManager.createDirectory(at: launchAgentsDirectory, withIntermediateDirectories: true)
    let plist = """
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0">
    <dict>
      <key>Label</key>
      <string>\(label)</string>
      <key>ProgramArguments</key>
      <array>
        <string>/usr/bin/python3</string>
        <string>\(scheduledScriptURL.path)</string>
        <string>--quit-codex</string>
        <string>--force-quit-codex</string>
        <string>--apply</string>
        <string>--write-report</string>
      </array>
      <key>StartCalendarInterval</key>
      <dict>
        <key>Weekday</key>
        <integer>1</integer>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
      </dict>
      <key>StandardOutPath</key>
      <string>\(stdoutURL.path)</string>
      <key>StandardErrorPath</key>
      <string>\(stderrURL.path)</string>
    </dict>
    </plist>
    """
    try plist.write(to: plistURL, atomically: true, encoding: .utf8)
  }

  private func resolveScriptURL() -> URL? {
    if let bundled = Bundle.main.url(forResource: "codex_weekly_maintenance", withExtension: "py") {
      return bundled
    }

    let installed = fileManager.homeDirectoryForCurrentUser
      .appendingPathComponent(".codex/skills/codex-maintenance/scripts/codex_weekly_maintenance.py")
    if fileManager.fileExists(atPath: installed.path) {
      return installed
    }

    return nil
  }

  private func runLaunchctl(_ arguments: [String], allowFailure: Bool = false) throws {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/bin/launchctl")
    process.arguments = arguments

    let pipe = Pipe()
    process.standardOutput = pipe
    process.standardError = pipe

    try process.run()
    process.waitUntilExit()

    if process.terminationStatus != 0 && !allowFailure {
      let data = pipe.fileHandleForReading.readDataToEndOfFile()
      let output = String(data: data, encoding: .utf8) ?? ""
      throw ScheduleError.launchctlFailed(output)
    }
  }
}

enum ScheduleError: LocalizedError {
  case missingScript
  case launchctlFailed(String)

  var errorDescription: String? {
    switch self {
    case .missingScript:
      return "Could not find the bundled maintenance script."
    case .launchctlFailed(let output):
      return output.isEmpty ? "launchctl failed." : output
    }
  }
}
