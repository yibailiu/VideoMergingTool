export interface MediaFile {
  path: string;
  name: string;
  display_width: number;
  display_height: number;
  video_codec: string;
  audio_codec: string | null;
  fps: string;
  duration: string;
  media_created_time: string;
  orientation: string;
  manual_rotation: number;
  planned_action: string;
  file_size: string;
  file_size_bytes: number;
}
export interface Issue {
  path: string;
  stage: string;
  reason: string;
}
export interface Health {
  path: string;
  status: string;
  level: string;
  reason: string;
}
export interface TaskResult {
  status: string;
  policy: string;
  check_level: string;
  checks: Health[];
  skipped: Issue[];
  outputs: string[];
  error: string;
}
export interface Plan {
  selected_count: number;
  copy_count: number;
  remux_count: number;
  audio_count: number;
  transcode_count: number;
  skipped_count: number;
  rotation_blocked_count: number;
  targets: { canvas: string; orientation: string }[];
}
export interface Settings {
  lang: string;
  mode: string;
  name: string;
  format: string;
  sortBy: string;
  outputDir: string;
  tempDir: string;
  codec: string;
  audioCodec: string;
  gpu: string;
  gpuWorkers: number;
  qualityProfile: string;
  crf: number;
  preset: string;
  fpsPolicy: string;
  resolutionPolicy: string;
  padColor: string;
  ffmpegPath: string;
  ffprobePath: string;
  recursive: boolean;
  overwrite: boolean;
  dryRun: boolean;
  keepTemp: boolean;
  autoDownloadDeps: boolean;
  notifyOnComplete: boolean;
  playSoundOnComplete: boolean;
  checkLevel: string;
  onError: string;
  columnWidths: Record<string, number>;
}
declare global {
  interface Window {
    __VMT__: { token: string; version: string; lang: string };
  }
}
