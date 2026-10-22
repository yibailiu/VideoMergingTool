import { describe, expect, it } from "vitest";
import { mergeOrderedFiles, visualGroups } from "./ordering";
import type { MediaFile } from "./types";

const file = (path: string, orientation: string) =>
  ({ path, orientation }) as MediaFile;
describe("source order and visual grouping", () => {
  it("never substitutes visual group order for the global merge order", () => {
    const files = [
      file("1", "portrait"),
      file("2", "landscape"),
      file("3", "square"),
      file("4", "portrait"),
    ];
    const groups = visualGroups(files, new Map());
    expect(groups.map((group) => group.key)).toEqual([
      "landscape",
      "portrait",
      "square",
    ]);
    expect(
      mergeOrderedFiles(files, new Set(["4", "2", "1", "3"])).map(
        (file) => file.path,
      ),
    ).toEqual(["1", "2", "3", "4"]);
  });
  it("retains the visual group after manual rotation and restores excluded sources in place", () => {
    const files = [
      file("1", "portrait"),
      file("2", "portrait"),
      file("3", "landscape"),
    ];
    const orientations = new Map([
      ["1", "landscape"],
      ["2", "portrait"],
      ["3", "landscape"],
    ]);
    expect(
      visualGroups(files, orientations)[0].files.map((file) => file.path),
    ).toEqual(["1", "3"]);
    const selected = new Set(["1", "3"]);
    expect(mergeOrderedFiles(files, selected).map((file) => file.path)).toEqual(
      ["1", "3"],
    );
    selected.add("2");
    expect(mergeOrderedFiles(files, selected).map((file) => file.path)).toEqual(
      ["1", "2", "3"],
    );
  });
});
