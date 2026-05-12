import AppKit
import SwiftUI

struct MenuBarContentView: View {
  @ObservedObject var runner: MaintenanceRunner
  @ObservedObject var schedule: ScheduleManager
  @ObservedObject var awake: CodexAwakeModel

  var body: some View {
    statusSection

    Divider()

    awakeSection

    Divider()

    maintenanceSection

    Divider()

    artifactSection

    Divider()

    archivedChatSection

    Divider()

    scheduleSection

    Divider()

    loginSection

    Divider()

    reportSection

    Divider()

    Button("Quit") {
      NSApplication.shared.terminate(nil)
    }
    .keyboardShortcut("q")
  }

  @ViewBuilder
  private var statusSection: some View {
    Text(runner.statusText)
      .font(.caption)

    Text(awake.statusText)
      .font(.caption)

    Text(awake.codexStatusText)
      .font(.caption)

    Text(schedule.statusText)
      .font(.caption)

    Text(schedule.loginStatusText)
      .font(.caption)
  }

  @ViewBuilder
  private var awakeSection: some View {
    Toggle(isOn: Binding(
      get: { awake.autoWhileCodexRuns },
      set: { awake.setAutoWhileCodexRuns($0) }
    )) {
      Label("Auto While Codex Runs", systemImage: "bolt.horizontal")
    }

    Button {
      awake.startManualSession(.indefinite)
    } label: {
      Label("Keep Awake Until Stopped", systemImage: "play.fill")
    }
    .disabled(awake.caffeinate.isRunning)

    Button {
      awake.startManualSession(.timed(60 * 60))
    } label: {
      Label("Keep Awake for 1 Hour", systemImage: "clock")
    }

    Button {
      awake.startManualSession(.timed(2 * 60 * 60))
    } label: {
      Label("Keep Awake for 2 Hours", systemImage: "clock.fill")
    }

    Button {
      awake.stopSession()
    } label: {
      Label(awake.stopTitle, systemImage: "stop.fill")
    }
    .disabled(!awake.caffeinate.isRunning)

    Button {
      openLockScreenSettings()
    } label: {
      Label("Open Lock Screen Settings", systemImage: "gearshape")
    }
  }

  @ViewBuilder
  private var maintenanceSection: some View {
    Button("Audit Now", action: runner.runAudit)
    .disabled(runner.isRunning)

    Button("Cleanup Now", action: runCleanupAfterConfirmation)
    .disabled(runner.isRunning)
  }

  @ViewBuilder
  private var artifactSection: some View {
    Button("Audit Workspace Artifacts", action: runner.runArtifactAudit)
    .disabled(runner.isRunning)

    Button("Clean Workspace Artifacts", action: runArtifactCleanupAfterConfirmation)
    .disabled(runner.isRunning)
  }

  @ViewBuilder
  private var archivedChatSection: some View {
    Button("Audit Archived Chats", action: runner.runArchivedAudit)
    .disabled(runner.isRunning)

    Button("Prune Archived Chats", action: runArchivedPruneAfterConfirmation)
    .disabled(runner.isRunning)
  }

  @ViewBuilder
  private var scheduleSection: some View {
    Button("Enable Weekly Cleanup") {
      schedule.enableWeeklyCleanup()
    }
    .disabled(schedule.isEnabled)

    Button("Disable Weekly Cleanup") {
      schedule.disableWeeklyCleanup()
    }
    .disabled(!schedule.isEnabled)

    Button("Schedule Folder") {
      schedule.openScheduleFolder()
    }
  }

  @ViewBuilder
  private var loginSection: some View {
    Button("Enable Start at Login") {
      schedule.enableStartAtLogin()
    }
    .disabled(schedule.opensAtLogin)

    Button("Disable Start at Login") {
      schedule.disableStartAtLogin()
    }
    .disabled(!schedule.opensAtLogin)
  }

  @ViewBuilder
  private var reportSection: some View {
    Button("Show Last Result") {
      runner.showLastResult()
    }
    .disabled(runner.lastResultText.isEmpty)

    Button("Open Latest Report") {
      runner.openLatestReport()
    }

    Button("Reports Folder") {
      runner.openReportsFolder()
    }

    Button("Backups Folder") {
      runner.openBackupsFolder()
    }

    Button("Copy Last Result") {
      runner.copyLastResult()
    }
    .disabled(runner.lastResultText.isEmpty && runner.lastOutput.isEmpty)
  }

  private func confirm(title: String, message: String) -> Bool {
    let alert = NSAlert()
    alert.messageText = title
    alert.informativeText = message
    alert.alertStyle = .warning
    alert.addButton(withTitle: "Continue")
    alert.addButton(withTitle: "Cancel")
    return alert.runModal() == .alertFirstButtonReturn
  }

  private func runCleanupAfterConfirmation() {
    if confirm(
      title: "Run Codex cleanup?",
      message: "This closes Codex, backs up local state, archives old active chats, rotates logs, and prunes stale workspace/config entries."
    ) {
      runner.runCleanup()
    }
  }

  private func runArtifactCleanupAfterConfirmation() {
    if confirm(
      title: "Clean generated workspace artifacts?",
      message: "This removes regenerable build folders, virtualenvs, caches, duplicate older version files, and derived page renders after writing a manifest."
    ) {
      runner.runArtifactCleanup()
    }
  }

  private func runArchivedPruneAfterConfirmation() {
    if confirm(
      title: "Prune archived chats?",
      message: "This closes Codex, backs up archived transcripts and state, removes archived chat records, and verifies the database afterward."
    ) {
      runner.runArchivedPrune()
    }
  }

  private func openLockScreenSettings() {
    guard let url = URL(string: "x-apple.systempreferences:com.apple.Lock-Screen-Settings.extension") else {
      return
    }
    NSWorkspace.shared.open(url)
  }
}
