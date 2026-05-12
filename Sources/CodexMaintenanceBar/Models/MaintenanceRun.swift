import Foundation

enum MaintenanceMode: String {
  case audit
  case cleanup
  case artifactAudit
  case artifactCleanup
  case archivedAudit
  case archivedPrune

  var displayName: String {
    switch self {
    case .audit:
      return "Audit"
    case .cleanup:
      return "Cleanup"
    case .artifactAudit:
      return "Artifact Audit"
    case .artifactCleanup:
      return "Artifact Cleanup"
    case .archivedAudit:
      return "Archived Chat Audit"
    case .archivedPrune:
      return "Archived Chat Prune"
    }
  }
}

enum MaintenanceState: Equatable {
  case idle
  case running(MaintenanceMode)
  case succeeded(MaintenanceMode)
  case failed(MaintenanceMode)
}

struct MaintenanceResult {
  let mode: MaintenanceMode
  let exitCode: Int32
  let output: String
  let reportURL: URL?
  let backupURL: URL?

  var succeeded: Bool {
    exitCode == 0
  }
}
