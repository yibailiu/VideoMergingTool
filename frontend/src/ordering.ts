import type { MediaFile } from "./types";

export function mergeOrderedFiles(
  files: MediaFile[],
  selected: Set<string>,
): MediaFile[] {
  return files.filter((file) => selected.has(file.path));
}

export function visualGroups(
  files: MediaFile[],
  orientations: Map<string, string>,
) {
  return ["landscape", "portrait", "square", "unknown"]
    .map((key) => ({
      key,
      files: files.filter(
        (file) => (orientations.get(file.path) || file.orientation) === key,
      ),
    }))
    .filter((group) => group.files.length);
}
