import AppKit
import Foundation

@MainActor
final class MaintenanceRunner: ObservableObject {
  @Published private(set) var state: MaintenanceState = .idle
  @Published private(set) var statusText = "Ready"
  @Published private(set) var lastOutput = ""
  @Published private(set) var lastReportURL: URL?
  @Published private(set) var lastBackupURL: URL?

  private let fileManager = FileManager.default

  var isRunning: Bool {
    if case .running = state {
      return true
    }
    return false
  }

  var didFail: Bool {
    if case .failed = state {
      return true
    }
    return false
  }

  var menuTitle: String {
    switch state {
    case .idle:
      return "Codex"
    case .running:
      return "Codex..."
    case .succeeded:
      return "Codex OK"
    case .failed:
      return "Codex !"
    }
  }

  var menuSymbol: String {
    switch state {
    case .idle:
      return "hammer"
    case .running:
      return "arrow.triangle.2.circlepath"
    case .succeeded:
      return "checkmark.circle"
    case .failed:
      return "exclamationmark.triangle"
    }
  }

  func runAudit() {
    run(.audit)
  }

  func runCleanup() {
    run(.cleanup)
  }

  func runArtifactAudit() {
    run(.artifactAudit)
  }

  func runArtifactCleanup() {
    run(.artifactCleanup)
  }

  func runArchivedAudit() {
    run(.archivedAudit)
  }

  func runArchivedPrune() {
    run(.archivedPrune)
  }

  func openLatestReport() {
    if let lastReportURL {
      NSWorkspace.shared.open(lastReportURL)
      return
    }

    guard let latest = latestFile(in: reportsDirectory, extension: "md") else {
      NSSound.beep()
      return
    }
    NSWorkspace.shared.open(latest)
  }

  func openReportsFolder() {
    openFolder(reportsDirectory)
  }

  func openBackupsFolder() {
    openFolder(codexHome.appendingPathComponent("maintenance_backups"))
  }

  func copyLastOutput() {
    guard !lastOutput.isEmpty else {
      NSSound.beep()
      return
    }
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(lastOutput, forType: .string)
  }

  private func run(_ mode: MaintenanceMode) {
    guard !isRunning else {
      return
    }

    state = .running(mode)
    statusText = "Running \(mode.displayName.lowercased())..."
    lastOutput = ""

    Task {
      let result = await runScript(mode)
      await MainActor.run {
        let reportURL = result.reportURL ?? self.latestFile(in: self.reportsDirectory, extension: "md")
        self.lastOutput = result.output
        self.lastReportURL = reportURL
        self.lastBackupURL = result.backupURL

        if result.succeeded {
          self.state = .succeeded(mode)
          self.statusText = "\(mode.displayName) finished"
        } else {
          self.state = .failed(mode)
          self.statusText = "\(mode.displayName) failed (\(result.exitCode))"
        }

        if let reportURL {
          NSWorkspace.shared.open(reportURL)
        }
      }
    }
  }

  private nonisolated func runScript(_ mode: MaintenanceMode) async -> MaintenanceResult {
    let scriptURL = resolveScriptURL(for: mode)
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
    process.arguments = arguments(for: mode, scriptURL: scriptURL)
    process.currentDirectoryURL = FileManager.default.homeDirectoryForCurrentUser
    process.environment = [
      "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin",
      "HOME": FileManager.default.homeDirectoryForCurrentUser.path
    ]

    let pipe = Pipe()
    process.standardOutput = pipe
    process.standardError = pipe

    do {
      try process.run()
    } catch {
      let output = "Could not run maintenance script at \(scriptURL.path): \(error.localizedDescription)"
      return MaintenanceResult(mode: mode, exitCode: 127, output: output, reportURL: nil, backupURL: nil)
    }

    process.waitUntilExit()
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    let output = String(data: data, encoding: .utf8) ?? ""

    return MaintenanceResult(
      mode: mode,
      exitCode: process.terminationStatus,
      output: output,
      reportURL: extractURL(from: output, prefix: "Report written to "),
      backupURL: extractURL(from: output, prefix: "Backup written to ")
    )
  }

  private nonisolated func arguments(for mode: MaintenanceMode, scriptURL: URL) -> [String] {
    switch mode {
    case .audit:
      return [scriptURL.path, "--write-report"]
    case .cleanup:
      return [scriptURL.path, "--quit-codex", "--force-quit-codex", "--apply", "--write-report"]
    case .artifactAudit:
      return [scriptURL.path, "--include-derived-page-renders"]
    case .artifactCleanup:
      return [scriptURL.path, "--apply", "--include-derived-page-renders"]
    case .archivedAudit:
      return [scriptURL.path]
    case .archivedPrune:
      return [scriptURL.path, "--quit-codex", "--force-quit-codex", "--apply"]
    }
  }

  private nonisolated func resolveScriptURL(for mode: MaintenanceMode) -> URL {
    let scriptName = scriptResourceName(for: mode)
    if let bundled = Bundle.main.url(forResource: scriptName, withExtension: "py") {
      return bundled
    }

    if mode == .audit || mode == .cleanup {
      let installed = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".codex/skills/codex-maintenance/scripts/codex_weekly_maintenance.py")
      if FileManager.default.fileExists(atPath: installed.path) {
        return installed
      }
    }

    return FileManager.default.homeDirectoryForCurrentUser
      .appendingPathComponent("\(scriptName).py")
  }

  private nonisolated func scriptResourceName(for mode: MaintenanceMode) -> String {
    switch mode {
    case .audit, .cleanup:
      return "codex_weekly_maintenance"
    case .artifactAudit, .artifactCleanup:
      return "codex_workspace_artifact_cleanup"
    case .archivedAudit, .archivedPrune:
      return "codex_archived_chat_prune"
    }
  }

  private nonisolated func extractURL(from output: String, prefix: String) -> URL? {
    for line in output.components(separatedBy: .newlines) {
      guard let range = line.range(of: prefix) else {
        continue
      }
      let path = String(line[range.upperBound...]).trimmingCharacters(in: .whitespacesAndNewlines)
      guard !path.isEmpty else {
        continue
      }
      return URL(fileURLWithPath: path)
    }
    return nil
  }

  private var codexHome: URL {
    fileManager.homeDirectoryForCurrentUser.appendingPathComponent(".codex")
  }

  private var reportsDirectory: URL {
    codexHome.appendingPathComponent("maintenance_reports")
  }

  private func openFolder(_ url: URL) {
    do {
      try fileManager.createDirectory(at: url, withIntermediateDirectories: true)
      NSWorkspace.shared.open(url)
    } catch {
      NSSound.beep()
    }
  }

  private func latestFile(in directory: URL, extension fileExtension: String) -> URL? {
    guard let files = try? fileManager.contentsOfDirectory(
      at: directory,
      includingPropertiesForKeys: [.contentModificationDateKey],
      options: [.skipsHiddenFiles]
    ) else {
      return nil
    }

    return files
      .filter { $0.pathExtension == fileExtension }
      .max { lhs, rhs in
        modificationDate(lhs) < modificationDate(rhs)
      }
  }

  private func modificationDate(_ url: URL) -> Date {
    let values = try? url.resourceValues(forKeys: [.contentModificationDateKey])
    return values?.contentModificationDate ?? .distantPast
  }
}
