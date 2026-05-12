import AppKit
import SwiftUI

struct MaintenanceResultWindowView: View {
  let title: String
  let subtitle: String
  let text: String
  let reportURL: URL?
  let backupURL: URL?

  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      HStack(alignment: .top, spacing: 12) {
        Image(systemName: title.localizedCaseInsensitiveContains("failed") ? "exclamationmark.triangle.fill" : "checkmark.circle.fill")
          .font(.title2)
          .foregroundStyle(title.localizedCaseInsensitiveContains("failed") ? .orange : .green)

        VStack(alignment: .leading, spacing: 3) {
          Text(title)
            .font(.headline)
          Text(subtitle)
            .font(.caption)
            .foregroundStyle(.secondary)
        }

        Spacer()
      }

      ScrollView {
        Text(text)
          .font(.system(.body, design: .default))
          .textSelection(.enabled)
          .frame(maxWidth: .infinity, alignment: .leading)
          .padding(12)
      }
      .background(Color(nsColor: .textBackgroundColor))
      .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
      .overlay(
        RoundedRectangle(cornerRadius: 8, style: .continuous)
          .stroke(Color(nsColor: .separatorColor), lineWidth: 1)
      )

      HStack {
        Button {
          NSPasteboard.general.clearContents()
          NSPasteboard.general.setString(text, forType: .string)
        } label: {
          Label("Copy Text", systemImage: "doc.on.doc")
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
    .padding(18)
    .frame(minWidth: 560, minHeight: 380)
  }
}
