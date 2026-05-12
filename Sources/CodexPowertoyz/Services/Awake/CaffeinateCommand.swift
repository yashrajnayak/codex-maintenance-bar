import Foundation

struct CaffeinateCommand: Equatable, Sendable {
  let executablePath: String
  let arguments: [String]

  init(
    executablePath: String = "/usr/bin/caffeinate",
    duration: TimeInterval? = nil,
    watchProcessIdentifier: Int32 = ProcessInfo.processInfo.processIdentifier
  ) {
    self.executablePath = executablePath

    var arguments = ["-dimsu", "-w", String(watchProcessIdentifier)]
    if let duration {
      arguments.append(contentsOf: ["-t", String(Int(duration.rounded()))])
    }
    self.arguments = arguments
  }
}
