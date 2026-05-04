import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
  func applicationDidFinishLaunching(_ notification: Notification) {
    NSApp.setActivationPolicy(.accessory)
  }
}

@main
struct CodexMaintenanceBarApp: App {
  @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
  @StateObject private var runner = MaintenanceRunner()

  var body: some Scene {
    MenuBarExtra {
      MenuBarContentView(runner: runner)
    } label: {
      Label(runner.menuTitle, systemImage: runner.menuSymbol)
    }
    .menuBarExtraStyle(.menu)
  }
}
