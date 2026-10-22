import {
  computed,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from "vue";
import { ElMessage } from "element-plus";
import { api } from "./api";
import { mergeOrderedFiles } from "./ordering";
import type { Issue, MediaFile, Plan, Settings, TaskResult } from "./types";

export function useWorkspace() {
  const fullLogText = ref("");
  const logDialogVisible = ref(false);
  const copyingLogs = ref(false);
  const settings = reactive<Settings>({
    lang: window.__VMT__.lang || "zh",
    mode: "optimal",
    name: "Merged_Output",
    format: "mp4",
    sortBy: "name-natural-asc",
    outputDir: "",
    tempDir: "",
    codec: "",
    audioCodec: "",
    gpu: "off",
    gpuWorkers: 1,
    qualityProfile: "balanced",
    crf: 23,
    preset: "medium",
    fpsPolicy: "majority",
    resolutionPolicy: "dominant",
    padColor: "black",
    ffmpegPath: "",
    ffprobePath: "",
    recursive: true,
    overwrite: false,
    dryRun: false,
    keepTemp: false,
    autoDownloadDeps: true,
    notifyOnComplete: true,
    playSoundOnComplete: false,
    checkLevel: "quick",
    onError: "stop",
    columnWidths: {},
  });
  const files = ref<MediaFile[]>([]),
    selected = ref(new Set<string>());
  const rotations = reactive<Record<string, number>>({}),
    orientations = reactive(new Map<string, string>());
  const inputDir = ref(""),
    sourceFiles = ref<string[]>([]),
    busy = ref(false),
    running = ref(false);
  const logs = ref<string[]>([]),
    progress = ref(0),
    result = ref<TaskResult | null>(null);
  const scanIssues = ref<Issue[]>([]),
    plan = ref<Plan | null>(null),
    deps = ref(""),
    depsReady = ref(false);
  const ready = ref(false),
    cursor = ref(0);
  let planVersion = 0,
    saveTimer: ReturnType<typeof setTimeout>,
    planTimer: ReturnType<typeof setTimeout>;
  let pollTimer: ReturnType<typeof setTimeout>,
    disposed = false,
    completionNotified = false;
  let runEpoch = 0;
  const zh = computed(() => settings.lang === "zh");
  const t = (cn: string, en: string) => (zh.value ? cn : en);
  const ordered = computed(() =>
    mergeOrderedFiles(files.value, selected.value),
  );
  function payload() {
    return {
      input_dir: inputDir.value,
      source_files: sourceFiles.value,
      selected_files: ordered.value.map((file) => file.path),
      rotation_overrides: { ...rotations },
      mode: settings.mode,
      name: settings.name,
      output_format: settings.format,
      sort_by: settings.sortBy,
      output_dir: settings.outputDir,
      temp_dir: settings.tempDir,
      video_codec: settings.codec,
      audio_codec: settings.audioCodec,
      gpu: settings.gpu,
      gpu_workers: settings.gpuWorkers,
      quality_profile: settings.qualityProfile,
      crf: settings.crf,
      preset: settings.preset,
      fps_policy: settings.fpsPolicy,
      resolution_policy: settings.resolutionPolicy,
      pad_color: settings.padColor,
      ffmpeg_path: settings.ffmpegPath,
      ffprobe_path: settings.ffprobePath,
      recursive: settings.recursive,
      overwrite: settings.overwrite,
      dry_run: settings.dryRun,
      keep_temp: settings.keepTemp,
      auto_download_deps: settings.autoDownloadDeps,
      check_level: settings.checkLevel,
      on_error: settings.onError,
    };
  }
  function failure(error: unknown) {
    ElMessage.error(String(error instanceof Error ? error.message : error));
  }
  async function checkDeps() {
    try {
      const data = await api("/deps");
      deps.value = data.message;
      depsReady.value = data.ok;
    } catch (error) {
      deps.value = String(error);
      depsReady.value = false;
    }
  }
  async function refreshPlan() {
    const version = ++planVersion;
    if (!files.value.length || running.value) return;
    try {
      const data = await api("/plan", payload());
      if (version === planVersion) {
        files.value = data.files;
        plan.value = data.plan;
      }
    } catch (error) {
      if (version === planVersion) failure(error);
    }
  }
  async function scan(reset = false) {
    if (!inputDir.value || running.value) return;
    busy.value = true;
    ++planVersion;
    try {
      const previous = new Set(files.value.map((file) => file.path));
      if (reset) {
        selected.value = new Set();
        orientations.clear();
        Object.keys(rotations).forEach((key) => delete rotations[key]);
      }
      const data = await api("/scan", payload());
      files.value = data.files;
      plan.value = data.plan;
      scanIssues.value = data.failures || [];
      files.value.forEach((file) => {
        if (reset || !previous.has(file.path)) selected.value.add(file.path);
        if (!orientations.has(file.path))
          orientations.set(file.path, file.orientation);
      });
      selected.value = new Set(
        [...selected.value].filter((path) =>
          files.value.some((file) => file.path === path),
        ),
      );
      await refreshPlan();
    } catch (error) {
      failure(error);
    } finally {
      busy.value = false;
    }
  }
  async function pickSource(kind: "files" | "folder") {
    if (running.value) return;
    try {
      const data = await api(
        kind === "files"
          ? `/pick-files?lang=${settings.lang}`
          : `/pick-folder?kind=source&lang=${settings.lang}`,
      );
      if (kind === "files" ? !data.paths?.length : !data.path) return;
      sourceFiles.value = kind === "files" ? data.paths : [];
      inputDir.value = kind === "files" ? data.input_dir : data.path;
      await scan(true);
    } catch (error) {
      failure(error);
    }
  }
  async function pickDirectory(field: "outputDir" | "tempDir") {
    try {
      const data = await api(
        `/pick-folder?kind=${field === "outputDir" ? "output" : "temp"}&lang=${settings.lang}`,
      );
      if (data.path) settings[field] = data.path;
    } catch (error) {
      failure(error);
    }
  }
  function toggle(path: string) {
    const next = new Set(selected.value);
    next.has(path) ? next.delete(path) : next.add(path);
    selected.value = next;
  }
  function rotate(path: string) {
    rotations[path] = ((rotations[path] || 0) + 90) % 360;
    refreshPlan();
  }
  async function openMedia(path: string) {
    try {
      await api("/open-media", { path });
    } catch (error) {
      failure(error);
    }
  }
  async function start() {
    if (running.value || busy.value) return;
    busy.value = true;
    ++runEpoch;
    try {
      if (
        settings.mode === "fast" &&
        ordered.value.some((file) => rotations[file.path])
      ) {
        ElMessage.warning(
          t(
            "旋转视频需要智能或强制合并。",
            "Rotated videos require Optimal or Extreme mode.",
          ),
        );
        return;
      }
      // Scan failures stay visible, and must participate in the chosen stop/skip policy.
      const request = payload();
      request.selected_files.push(
        ...scanIssues.value.map((issue) => issue.path),
      );
      await api("/merge", request);
      cursor.value = 0;
      logs.value = [];
      result.value = null;
      progress.value = 0;
      running.value = true;
      completionNotified = false;
    } catch (error) {
      failure(error);
    } finally {
      busy.value = false;
    }
  }
  async function cancel() {
    try {
      await api("/cancel", {});
    } catch (error) {
      failure(error);
    }
  }
  async function retryFailures() {
    if (!result.value) return;
    const paths = [...new Set(result.value.skipped.map((issue) => issue.path))];
    if (!paths.length) return;
    sourceFiles.value = paths;
    await scan(true);
  }
  function excludeScanIssue(path: string) {
    scanIssues.value = scanIssues.value.filter((issue) => issue.path !== path);
  }
  async function showFullLogs() {
    try {
      const data = await api("/logs");
      fullLogText.value = data.text;
      logDialogVisible.value = true;
    } catch (error) {
      failure(error);
    }
  }
  async function copyLogs() {
    copyingLogs.value = true;
    try {
      const data = await api("/copy-logs", {});
      if (data.copied) {
        ElMessage.success(
          t("完整日志已复制到剪贴板", "Full log copied to clipboard"),
        );
      } else {
        fullLogText.value = data.text;
        logDialogVisible.value = true;
        ElMessage.warning(
          t(
            "系统复制失败，请在完整日志中按 Ctrl+A / Ctrl+C（Mac 使用 ⌘）复制。",
            "System copy failed. Select and copy from the full log view (Ctrl+A / Ctrl+C, or ⌘ on Mac).",
          ),
        );
      }
    } catch (error) {
      failure(error);
      await showFullLogs();
    } finally {
      copyingLogs.value = false;
    }
  }
  async function poll() {
    const epoch = runEpoch;
    try {
      const data = await api("/status?after=" + cursor.value);
      if (epoch !== runEpoch) return;
      if (data.log_cursor < cursor.value) logs.value = [];
      cursor.value = data.log_cursor;
      logs.value.push(...data.logs);
      const wasRunning = running.value;
      running.value = data.running;
      progress.value = data.progress;
      if (
        data.result &&
        JSON.stringify(data.result) !== JSON.stringify(result.value)
      )
        result.value = data.result;
      if (!data.running && !data.result) progress.value = 0;
      if (wasRunning && !data.running && !completionNotified) {
        completionNotified = true;
        if (settings.notifyOnComplete) {
          const status = result.value?.status;
          await api("/notify", {
            title: "VideoMergingTool",
            body:
              status === "completed"
                ? t("合并完成", "Merge completed")
                : status === "partial"
                  ? t(
                      "部分完成，请查看跳过清单",
                      "Partially completed; review skipped files",
                    )
                  : t(
                      "任务已结束，请查看结果",
                      "Task ended; review the result",
                    ),
            sound: settings.playSoundOnComplete,
          });
        }
      }
    } catch {
      /* A transient status request must not interrupt processing. */
    } finally {
      if (!disposed) pollTimer = setTimeout(poll, running.value ? 500 : 1400);
    }
  }
  watch(
    settings,
    () => {
      if (!ready.value) return;
      clearTimeout(saveTimer);
      saveTimer = setTimeout(
        () => api("/config", { ...settings }).catch(failure),
        300,
      );
      clearTimeout(planTimer);
      planTimer = setTimeout(refreshPlan, 160);
    },
    { deep: true },
  );
  watch(selected, () => {
    clearTimeout(planTimer);
    planTimer = setTimeout(refreshPlan, 100);
  });
  watch(
    () => [settings.sortBy, settings.recursive],
    () => {
      if (ready.value) scan();
    },
  );
  onMounted(async () => {
    try {
      const config = await api("/config");
      Object.assign(settings, config);
      if (Array.isArray(settings.columnWidths)) settings.columnWidths = {};
    } catch (error) {
      failure(error);
    }
    ready.value = true;
    checkDeps();
    poll();
  });
  onBeforeUnmount(() => {
    disposed = true;
    clearTimeout(saveTimer);
    clearTimeout(planTimer);
    clearTimeout(pollTimer);
  });
  return {
    settings,
    files,
    selected,
    rotations,
    orientations,
    inputDir,
    busy,
    running,
    logs,
    progress,
    result,
    scanIssues,
    plan,
    deps,
    depsReady,
    zh,
    t,
    ordered,
    scan,
    pickSource,
    pickDirectory,
    toggle,
    rotate,
    openMedia,
    start,
    cancel,
    checkDeps,
    copyLogs,
    showFullLogs,
    fullLogText,
    logDialogVisible,
    copyingLogs,
    retryFailures,
    excludeScanIssue,
  };
}
