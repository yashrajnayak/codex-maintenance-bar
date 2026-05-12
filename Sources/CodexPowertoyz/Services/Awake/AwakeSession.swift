import Foundation

enum AwakeSession: Equatable, Sendable {
  case indefinite
  case timed(TimeInterval)

  var duration: TimeInterval? {
    switch self {
    case .indefinite:
      return nil
    case .timed(let duration):
      return duration
    }
  }

  var displayName: String {
    switch self {
    case .indefinite:
      return "Until stopped"
    case .timed(let duration):
      let minutes = Int(duration / 60)
      if minutes >= 60 {
        let hours = minutes / 60
        return hours == 1 ? "1 hour" : "\(hours) hours"
      }
      return "\(minutes) minutes"
    }
  }
}
