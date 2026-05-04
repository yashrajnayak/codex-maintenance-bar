import AppKit
import SwiftUI

struct MenuBarContentView: View {
  @ObservedObject var runner: MaintenanceRunner
  @ObservedObject var schedule: ScheduleManager

  var body: some View {
    Text(runner.statusText)
      .font(.caption)

    Text(schedule.statusText)
      .font(.caption)

    Text(schedule.loginStatusText)
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

    Divider()

    Button("Enable Start at Login") {
      schedule.enableStartAtLogin()
    }
    .disabled(schedule.opensAtLogin)

    Button("Disable Start at Login") {
      schedule.disableStartAtLogin()
    }
    .disabled(!schedule.opensAtLogin)

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
