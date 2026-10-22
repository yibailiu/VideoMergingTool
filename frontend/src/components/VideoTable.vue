<script setup lang="ts">
import { computed, defineComponent, h, nextTick, ref, watch } from "vue";
import { AgGridVue } from "ag-grid-vue3";
import {
  AllCommunityModule,
  ModuleRegistry,
  themeQuartz,
  type ColDef,
  type GridApi,
} from "ag-grid-community";
import { ElButton, ElCheckbox, ElTag, ElTooltip } from "element-plus";
import { RefreshRight, Minus, Plus, VideoPlay } from "@element-plus/icons-vue";
import type { Health, MediaFile } from "../types";
import { visualGroups } from "../ordering";

ModuleRegistry.registerModules([AllCommunityModule]);
const props = defineProps<{
  files: MediaFile[];
  selected: Set<string>;
  orientations: Map<string, string>;
  rotations: Record<string, number>;
  widths: Record<string, number>;
  checks: Health[];
  disabled: boolean;
  zh: boolean;
}>();
const emit = defineEmits([
  "toggle",
  "rotate",
  "open",
  "widths",
  "selectAll",
  "clear",
]);
const api = ref<GridApi>(),
  sizing = ref(false);
const t = (cn: string, en: string) => (props.zh ? cn : en);
const orientationName = (key: string) =>
  ({
    landscape: t("横向视频", "Landscape"),
    portrait: t("竖向视频", "Portrait"),
    square: t("同比例视频", "Square"),
    unknown: t("其他视频", "Other"),
  })[key] || key;
const rows = computed(() =>
  visualGroups(props.files, props.orientations).flatMap((group) => [
    {
      path: "group:" + group.key,
      group: true,
      label: orientationName(group.key),
      count: group.files.length,
    },
    ...group.files,
  ]),
);
const actionName = (action: string) =>
  ({
    copy: t("直接合并", "Stream copy"),
    remux: t("重新封装", "Remux"),
    audio: t("音频转码", "Audio encode"),
    transcode: t("视频转码", "Video encode"),
    excluded: t("已排除", "Excluded"),
    skipped: t("无兼容视频", "No compatible peer"),
    rotation_required: t("旋转需要转码", "Rotation requires encoding"),
  })[action] || action;
const healthName = (file: MediaFile) => {
  const item = props.checks.find((check) => check.path === file.path);
  if (!item) return t("待检查", "Not checked");
  if (item.status === "error") return t("检测到异常", "Input error");
  if (item.status === "unknown") return t("无法确定", "Undetermined");
  return item.level === "quick"
    ? t("抽检通过", "Sample passed")
    : item.level === "full"
      ? t("解码检查通过", "Decode passed")
      : t("基础检查通过", "Metadata passed");
};
const NameCell = defineComponent({
  props: ["params"],
  setup(p) {
    return () =>
      h("div", { class: "name-cell" }, [
        h(
          ElButton,
          {
            link: true,
            type: "primary",
            title: p.params.data.path,
            onClick: () => emit("open", p.params.data.path),
          },
          {
            default: () => [
              h(VideoPlay, { class: "small-icon" }),
              p.params.data.name,
            ],
          },
        ),
        props.rotations[p.params.data.path]
          ? h(
              ElTag,
              { size: "small" },
              () => `${props.rotations[p.params.data.path]}°`,
            )
          : null,
      ]);
  },
});
const SelectCell = defineComponent({
  props: ["params"],
  setup(p) {
    return () =>
      h(ElCheckbox, {
        modelValue: props.selected.has(p.params.data.path),
        disabled: props.disabled,
        "aria-label": t("选择 ", "Select ") + p.params.data.name,
        "onUpdate:modelValue": () => emit("toggle", p.params.data.path),
      });
  },
});
const ActionCell = defineComponent({
  props: ["params"],
  setup(p) {
    return () =>
      h("div", { class: "file-actions" }, [
        h(
          ElTooltip,
          {
            showAfter: 450,
            enterable: false,
            popperClass: "action-tooltip",
            content: t(
              "顺时针旋转 90°（不修改源文件）",
              "Rotate clockwise 90° (source unchanged)",
            ),
          },
          {
            default: () =>
              h(
                ElButton,
                {
                  circle: true,
                  size: "small",
                  disabled: props.disabled,
                  "aria-label": t("旋转 ", "Rotate ") + p.params.data.name,
                  onClick: () => emit("rotate", p.params.data.path),
                },
                { icon: () => h(RefreshRight) },
              ),
          },
        ),
        h(
          ElTooltip,
          {
            showAfter: 450,
            enterable: false,
            popperClass: "action-tooltip",
            content: props.selected.has(p.params.data.path)
              ? t("从本次合并排除", "Exclude from this merge")
              : t("重新加入本次合并", "Include again"),
          },
          {
            default: () =>
              h(
                ElButton,
                {
                  circle: true,
                  size: "small",
                  disabled: props.disabled,
                  "aria-label":
                    t("切换排除 ", "Toggle exclusion ") + p.params.data.name,
                  onClick: () => emit("toggle", p.params.data.path),
                },
                {
                  icon: () =>
                    h(props.selected.has(p.params.data.path) ? Minus : Plus),
                },
              ),
          },
        ),
      ]);
  },
});
const GroupCell = defineComponent({
  props: ["params"],
  setup(p) {
    return () =>
      h("div", { class: "video-group" }, [
        h("span", { class: "group-dot" }),
        h("strong", p.params.data.label),
        h("span", `${p.params.data.count} ${t("个视频", "videos")}`),
      ]);
  },
});
const theme = themeQuartz.withParams({
  backgroundColor: "#171d28",
  foregroundColor: "#d8e0ef",
  headerBackgroundColor: "#202837",
  headerTextColor: "#9faec5",
  borderColor: "#303b4e",
  accentColor: "#6da5ff",
  fontFamily: "system-ui, sans-serif",
  fontSize: 12,
  rowHeight: 48,
  headerHeight: 42,
  wrapperBorderRadius: 10,
});
const columns = computed<ColDef[]>(() => [
  {
    colId: "selected",
    headerName: "",
    width: 48,
    minWidth: 48,
    pinned: "left",
    resizable: false,
    cellRenderer: SelectCell,
  },
  {
    field: "name",
    headerName: t("文件名", "Filename"),
    minWidth: 180,
    flex: 1,
    cellRenderer: NameCell,
    tooltipField: "path",
  },
  {
    colId: "resolution",
    headerName: t("分辨率", "Resolution"),
    valueGetter: (p) => `${p.data.display_width} × ${p.data.display_height}`,
  },
  {
    colId: "codec",
    headerName: t("编码", "Codec"),
    valueGetter: (p) => `${p.data.video_codec} / ${p.data.audio_codec || "—"}`,
  },
  { field: "fps", headerName: "FPS" },
  { field: "duration", headerName: t("时长", "Duration") },
  {
    field: "media_created_time",
    headerName: t("媒体创建日期", "Media created"),
  },
  { field: "file_size", headerName: t("大小", "Size") },
  {
    colId: "health",
    headerName: t("文件检查", "Input check"),
    valueGetter: (p) => healthName(p.data),
  },
  {
    field: "planned_action",
    headerName: t("处理方式", "Processing"),
    valueFormatter: (p) => actionName(p.value),
  },
  {
    colId: "actions",
    headerName: t("操作", "Actions"),
    width: 100,
    minWidth: 100,
    pinned: "right",
    cellRenderer: ActionCell,
  },
]);
function fit(resetField?: string) {
  if (!api.value) return;
  sizing.value = true;
  const canvas = document.createElement("canvas"),
    ctx = canvas.getContext("2d")!;
  ctx.font = "12px system-ui, sans-serif";
  const content: Record<string, string[]> = {
    resolution: props.files.map(
      (f) => `${f.display_width} × ${f.display_height}`,
    ),
    codec: props.files.map((f) => `${f.video_codec} / ${f.audio_codec || "—"}`),
    fps: props.files.map((f) => f.fps),
    duration: props.files.map((f) => f.duration),
    media_created_time: props.files.map((f) => f.media_created_time),
    file_size: props.files.map((f) => f.file_size),
    health: props.files.map(healthName),
    planned_action: props.files.map((f) => actionName(f.planned_action)),
  };
  for (const col of columns.value) {
    const id = col.colId || col.field!;
    if (id === "selected") continue;
    const saved = resetField === id ? 0 : Number(props.widths[id]) || 0;
    if (id === "name") {
      if (saved)
        api.value.setColumnWidths([
          { key: id, newWidth: Math.max(180, saved) },
        ]);
      else
        api.value.applyColumnState({
          state: [{ colId: id, flex: 1, width: 200 }],
        });
      continue;
    }
    const natural =
      id === "actions"
        ? 100
        : Math.max(
            72,
            Math.ceil(
              Math.max(
                ...[col.headerName || "", ...(content[id] || [])].map(
                  (text) => ctx.measureText(text).width,
                ),
              ),
            ) + 36,
          );
    api.value.setColumnWidths([
      { key: id, newWidth: Math.max(natural, saved) },
    ]);
  }
  sizing.value = false;
}
function resized(event: any) {
  if (sizing.value || !event.finished || event.source !== "uiColumnResized")
    return;
  const values = { ...props.widths };
  for (const col of event.columns || [])
    values[col.getColId()] = col.getActualWidth();
  emit("widths", values);
  nextTick(() => fit());
}
function resetWidths() {
  emit("widths", {});
  nextTick(() => fit());
}
watch(
  [rows, () => props.checks, () => props.selected, () => props.zh],
  async () => {
    await nextTick();
    api.value?.refreshCells({ force: true });
    fit();
  },
  { deep: true },
);
</script>

<template>
  <section class="video-panel">
    <div class="table-toolbar">
      <div class="toolbar-buttons">
        <el-button
          size="small"
          :disabled="disabled || !files.length"
          @click="emit('selectAll')"
          >{{ t("全选", "Select all") }}</el-button
        ><el-button
          size="small"
          :disabled="disabled || !files.length"
          @click="emit('clear')"
          >{{ t("取消全选", "Clear selection") }}</el-button
        ><span
          >{{ t("已选", "Selected") }} {{ selected.size }}/{{
            files.length
          }}</span
        >
      </div>
      <el-button link type="primary" @click="resetWidths"
        >↔ {{ t("重置列宽", "Reset widths") }}</el-button
      >
    </div>
    <p class="table-hint">
      {{
        t(
          "横竖分组仅用于查看，合并按全局规则排序。拖动表头分隔线调整列宽。",
          "Groups are visual only; merge uses global ordering. Drag header separators to resize.",
        )
      }}
    </p>
    <AgGridVue
      class="video-grid"
      :theme="theme"
      :column-defs="columns"
      :row-data="rows"
      :default-col-def="{
        resizable: true,
        sortable: false,
        suppressMovable: true,
        minWidth: 72,
      }"
      :get-row-id="(p: any) => p.data.path"
      :is-full-width-row="(p: any) => !!p.rowNode.data?.group"
      :full-width-cell-renderer="GroupCell"
      :get-row-height="(p: any) => (p.data?.group ? 36 : 48)"
      :get-row-class="
        (p: any) =>
          !p.data.group && !selected.has(p.data.path) ? 'excluded-row' : ''
      "
      :animate-rows="false"
      :suppress-cell-focus="true"
      :overlay-no-rows-template="`<span>${t('选择文件夹或视频，开始整理你的合并任务', 'Choose a folder or videos to prepare your merge')}</span>`"
      @grid-ready="
        (event: any) => {
          api = event.api;
          fit();
        }
      "
      @first-data-rendered="fit()"
      @column-resized="resized"
    />
  </section>
</template>
