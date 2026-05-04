import AppKit
import SwiftUI

struct MenuBarContentView: View {
  @ObservedObject var runner: MaintenanceRunner

  var body: some View {
    Text(runner.statusText)
      .font(.caption)

    Divider()

    Button("Audit Now") {
      runner.runAudit()
    }
    .disabled(runner.isRunning)

    Button("Cleanup Now") {
      runner.runCleanup()
    }
    .disabled(runner.isRunning)

    Divider()

    Button("Open Latest Report") {
      runner.openLatestReport()
    }

    Button("Reports Folder") {
      runner.openReportsFolder()
    }

    Button("Backups Folder") {
      runner.openBackupsFolder()
    }

    Button("Copy Last Output") {
      runner.copyLastOutput()
    }
    .disabled(runner.lastOutput.isEmpty)

    Divider()

    Button("Quit") {
      NSApplication.shared.terminate(nil)
    }
    .keyboardShortcut("q")
  }
}
