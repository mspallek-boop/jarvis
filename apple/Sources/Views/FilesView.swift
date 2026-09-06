import SwiftUI

struct FilesView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Group {
                if model.isLoadingFiles && model.files.isEmpty {
                    ProgressView("Mac wird verbunden …")
                } else {
                    List(model.files) { item in
                        HStack(spacing: 12) {
                            Image(systemName: item.is_directory ? "folder.fill" : icon(for: item.name))
                                .foregroundStyle(item.is_directory ? Color.primary : .secondary)
                                .frame(width: 24)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(item.name).lineLimit(1)
                                    .font(model.appFont(.body))
                                if !item.is_directory {
                                    Text(ByteCountFormatter.string(fromByteCount: item.size, countStyle: .file))
                                        .font(model.appFont(.caption)).foregroundStyle(.secondary)
                                }
                            }
                            Spacer()
                            if item.is_directory {
                                Image(systemName: "chevron.right").foregroundStyle(.tertiary)
                            } else {
                                Button {
                                    Task { await model.download(item) }
                                } label: { Image(systemName: "arrow.down.circle") }
                                .buttonStyle(.plain)
                            }
                        }
                        .contentShape(Rectangle())
                        .onTapGesture {
                            if item.is_directory { Task { await model.loadFiles(path: item.path) } }
                        }
                    }
                }
            }
            .navigationTitle("Mac-Dateien")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Schließen") { dismiss() } }
                ToolbarItem {
                    if let path = model.filePath, let parent = model.fileParent, path != parent {
                        Button { Task { await model.loadFiles(path: parent) } } label: { Image(systemName: "arrow.up") }
                    }
                }
                ToolbarItem {
                    if let file = model.downloadedFile {
                        ShareLink(item: file) { Image(systemName: "square.and.arrow.up") }
                    }
                }
            }
            .task { if model.files.isEmpty { await model.loadFiles() } }
            .alert("JARVIS", isPresented: Binding(
                get: { model.lastError != nil },
                set: { if !$0 { model.lastError = nil } }
            )) { Button("OK") { model.lastError = nil } } message: {
                Text(model.lastError ?? "")
            }
        }
        #if os(macOS)
        .frame(minWidth: 650, minHeight: 560)
        #endif
        .font(model.appFont(.body))
        .tint(.blue)
    }

    private func icon(for name: String) -> String {
        let suffix = (name as NSString).pathExtension.lowercased()
        if ["jpg", "jpeg", "png", "heic"].contains(suffix) { return "photo" }
        if ["mov", "mp4", "m4v"].contains(suffix) { return "film" }
        if suffix == "pdf" { return "doc.richtext" }
        if ["zip", "tar", "gz"].contains(suffix) { return "archivebox" }
        return "doc"
    }
}
