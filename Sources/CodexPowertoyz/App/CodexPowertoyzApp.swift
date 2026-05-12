import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
  func applicationDidFinishLaunching(_ notification: Notification) {
    NSApp.setActivationPolicy(.accessory)
  }
}

@main
struct CodexPowertoyzApp: App {
  @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
  @StateObject private var runner = MaintenanceRunner()
  @StateObject private var schedule = ScheduleManager()
  @StateObject private var awake = CodexAwakeModel()

  var body: some Scene {
    MenuBarExtra {
      MenuBarContentView(runner: runner, schedule: schedule, awake: awake)
    } label: {
      Label(menuTitle, systemImage: menuSymbol)
    }
    .menuBarExtraStyle(.menu)
  }

  private var menuTitle: String {
    if runner.isRunning {
      return runner.menuTitle
    }
    if awake.caffeinate.isRunning {
      return "Powertoyz Awake"
    }
    return "Powertoyz"
  }

  private var menuSymbol: String {
    if runner.isRunning || runner.didFail {
      return runner.menuSymbol
    }
    if awake.caffeinate.isRunning {
      return "bolt.fill"
    }
    return "wand.and.stars"
  }
}
