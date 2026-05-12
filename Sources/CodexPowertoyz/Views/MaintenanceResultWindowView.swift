import AppKit
import SwiftUI

struct MaintenanceResultWindowView: View {
  let title: String
  let subtitle: String
  let text: String
  let reportURL: URL?
  let backupURL: URL?

  private var report: MaintenanceReportPresentation {
    MaintenanceReportPresentation(markdown: text, fallbackTitle: title)
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      header

      ScrollView {
        VStack(alignment: .leading, spacing: 18) {
          summaryGrid

          ForEach(report.sections) { section in
            reportSection(section)
          }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 2)
      }

      footer
    }
    .padding(18)
    .frame(minWidth: 620, minHeight: 430)
  }

  private var header: some View {
    HStack(alignment: .top, spacing: 12) {
      Image(systemName: title.localizedCaseInsensitiveContains("failed") ? "exclamationmark.triangle.fill" : "checkmark.circle.fill")
        .font(.title2)
        .foregroundStyle(title.localizedCaseInsensitiveContains("failed") ? .orange : .green)

      VStack(alignment: .leading, spacing: 3) {
        Text(report.title)
          .font(.headline)
        Text(subtitle)
          .font(.caption)
          .foregroundStyle(.secondary)
      }

      Spacer()
    }
  }

  private var summaryGrid: some View {
    VStack(alignment: .leading, spacing: 10) {
      Text("Summary")
        .font(.subheadline.weight(.semibold))

      LazyVGrid(columns: [GridItem(.adaptive(minimum: 190), spacing: 10)], alignment: .leading, spacing: 10) {
        ForEach(report.summaryItems) { item in
          VStack(alignment: .leading, spacing: 5) {
            Text(item.key)
              .font(.caption)
              .foregroundStyle(.secondary)
            Text(item.value)
              .font(.body.weight(.medium))
              .textSelection(.enabled)
              .lineLimit(3)
          }
          .padding(10)
          .frame(maxWidth: .infinity, alignment: .leading)
          .background(Color(nsColor: .controlBackgroundColor))
          .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
          .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
              .stroke(Color(nsColor: .separatorColor), lineWidth: 1)
          )
        }
      }
    }
  }

  private func reportSection(_ section: MaintenanceReportSection) -> some View {
    VStack(alignment: .leading, spacing: 10) {
      Text(section.title)
        .font(.subheadline.weight(.semibold))

      VStack(alignment: .leading, spacing: 0) {
        ForEach(section.items) { item in
          HStack(alignment: .firstTextBaseline, spacing: 10) {
            VStack(alignment: .leading, spacing: 3) {
              Text(item.primary)
                .font(.body)
                .lineLimit(2)
                .textSelection(.enabled)

              if let secondary = item.secondary {
                Text(secondary)
                  .font(.caption.monospaced())
                  .foregroundStyle(.secondary)
                  .lineLimit(1)
                  .textSelection(.enabled)
              }
            }

            Spacer(minLength: 12)

            if let trailing = item.trailing {
              Text(trailing)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(Color(nsColor: .controlBackgroundColor))
                .clipShape(Capsule())
            }
          }
          .padding(.vertical, 8)

          if item.id != section.items.last?.id {
            Divider()
          }
        }
      }
      .padding(.horizontal, 10)
      .background(Color(nsColor: .textBackgroundColor))
      .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
      .overlay(
        RoundedRectangle(cornerRadius: 8, style: .continuous)
          .stroke(Color(nsColor: .separatorColor), lineWidth: 1)
      )
    }
  }

  private var footer: some View {
    HStack {
      Button {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
      } label: {
        Label("Copy Full Report", systemImage: "doc.on.doc")
      }

      if let reportURL {
        Button {
          NSWorkspace.shared.open(reportURL)
        } label: {
          Label("Open Report File", systemImage: "doc.text")
        }
      }

      if let backupURL {
        Button {
          NSWorkspace.shared.open(backupURL)
        } label: {
          Label("Open Backup", systemImage: "externaldrive")
        }
      }

      Spacer()
    }
  }
}

private struct MaintenanceReportPresentation {
  let title: String
  let summaryItems: [MaintenanceReportSummaryItem]
  let sections: [MaintenanceReportSection]

  init(markdown: String, fallbackTitle: String) {
    let lines = markdown.components(separatedBy: .newlines)
    let heading = lines.first { $0.hasPrefix("# ") }
      .map { Self.clean($0.replacingOccurrences(of: "# ", with: "")) }
    title = heading?.isEmpty == false ? heading! : fallbackTitle

    var summaryItems: [MaintenanceReportSummaryItem] = []
    var sections: [MaintenanceReportSection] = []
    var currentSectionTitle: String?
    var currentItems: [MaintenanceReportListItem] = []

    func flushSection() {
      guard let currentSectionTitle, !currentItems.isEmpty else {
        currentItems = []
        return
      }
      sections.append(MaintenanceReportSection(title: currentSectionTitle, items: currentItems))
      currentItems = []
    }

    for rawLine in lines.dropFirst() {
      let line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
      guard !line.isEmpty else {
        continue
      }

      if line.hasPrefix("## ") {
        flushSection()
        currentSectionTitle = Self.clean(line.replacingOccurrences(of: "## ", with: ""))
        continue
      }

      guard line.hasPrefix("- ") else {
        continue
      }

      let bullet = String(line.dropFirst(2))

      if currentSectionTitle == nil, let item = Self.summaryItem(from: bullet) {
        summaryItems.append(item)
      } else if let item = Self.listItem(from: bullet) {
        currentItems.append(item)
      }
    }

    flushSection()

    let fallbackSummary = summaryItems.isEmpty
      ? [MaintenanceReportSummaryItem(key: "Result", value: Self.clean(markdown))]
      : summaryItems
    self.summaryItems = Array(fallbackSummary.prefix(12))
    self.sections = sections.map { section in
      MaintenanceReportSection(title: section.title, items: Array(section.items.prefix(25)))
    }
  }

  private static func summaryItem(from bullet: String) -> MaintenanceReportSummaryItem? {
    guard let separator = bullet.firstIndex(of: ":") else {
      return nil
    }

    let key = clean(String(bullet[..<separator]))
    let rawValue = clean(String(bullet[bullet.index(after: separator)...]))
    guard !key.isEmpty, !rawValue.isEmpty else {
      return nil
    }

    return MaintenanceReportSummaryItem(key: key, value: displayValue(rawValue, key: key))
  }

  private static func listItem(from bullet: String) -> MaintenanceReportListItem? {
    let parts = bullet.components(separatedBy: "|").map { clean($0) }
    if parts.count >= 3, parts[0].localizedCaseInsensitiveContains("bytes") {
      let bytes = Int64(parts[0].components(separatedBy: CharacterSet.decimalDigits.inverted).joined())
      let trailing = bytes.map { ByteCountFormatter.string(fromByteCount: $0, countStyle: .file) } ?? parts[0]
      return MaintenanceReportListItem(primary: parts.dropFirst(2).joined(separator: " | "), secondary: parts[1], trailing: trailing)
    }

    let cleaned = clean(bullet)
    return cleaned.isEmpty ? nil : MaintenanceReportListItem(primary: cleaned, secondary: nil, trailing: nil)
  }

  private static func displayValue(_ value: String, key: String) -> String {
    if key.localizedCaseInsensitiveContains("mode") {
      if value == "dry-run" {
        return "Dry run (no changes made)"
      }
      if value == "apply" {
        return "Apply (changes made)"
      }
    }
    let digits = value.components(separatedBy: CharacterSet.decimalDigits.inverted).joined()
    if key.localizedCaseInsensitiveContains("bytes"), let bytes = Int64(digits) {
      return "\(ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)) (\(bytes) bytes)"
    }
    if value == "none (dry-run)" {
      return "None (dry run)"
    }
    return value
  }

  private static func clean(_ value: String) -> String {
    value
      .replacingOccurrences(of: "`", with: "")
      .replacingOccurrences(of: "**", with: "")
      .trimmingCharacters(in: .whitespacesAndNewlines)
  }
}

private struct MaintenanceReportSummaryItem: Identifiable {
  let id = UUID()
  let key: String
  let value: String
}

private struct MaintenanceReportSection: Identifiable {
  let id = UUID()
  let title: String
  let items: [MaintenanceReportListItem]
}

private struct MaintenanceReportListItem: Identifiable {
  let id = UUID()
  let primary: String
  let secondary: String?
  let trailing: String?
}
