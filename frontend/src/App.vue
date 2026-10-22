<script setup lang="ts">
import { computed } from "vue";
import {
  FolderOpened,
  DocumentAdd,
  Refresh,
  VideoPlay,
  CircleClose,
} from "@element-plus/icons-vue";
import zhCn from "element-plus/es/locale/lang/zh-cn";
import en from "element-plus/es/locale/lang/en";
import { api } from "./api";
import { useWorkspace } from "./useWorkspace";
import VideoTable from "./components/VideoTable.vue";
import SettingsPanel from "./components/SettingsPanel.vue";
import LogPanel from "./components/LogPanel.vue";
import TaskResult from "./components/TaskResult.vue";
import appIcon from "../../assets/icons/VideoMergingTool.png";
const w = useWorkspace();
const {
  settings,
  files,
  selected,
  orientations,
  rotations,
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
  fullLogText,
  logDialogVisible,
  copyingLogs,
} = w;
const version = window.__VMT__.version;
const statusText = computed(() => {
  if (running.value) return t("正在处理", "Processing");
  if (result.value?.status === "partial")
    return t("部分完成", "Partially completed");
  if (result.value?.status === "completed") return t("合并完成", "Completed");
  if (result.value?.status === "failed") return t("任务失败", "Task failed");
  if (result.value?.status === "cancelled") return t("已取消", "Cancelled");
  return files.value.length
    ? t("准备就绪", "Ready")
    : t("等待添加视频", "Add videos to begin");
});
const checks = computed(() => result.value?.checks || []);
</script>
<template>
  <el-config-provider :locale="zh ? zhCn : en">
    <div class="app-shell">
      <header class="app-header">
        <div class="brand">
          <img :src="appIcon" class="app-logo" alt="VideoMergingTool" />
          <span>VideoMergingTool</span
          ><el-tag size="small" effect="plain">{{ version }}</el-tag>
        </div>
        <div class="header-actions">
          <el-tooltip :content="deps"
            ><el-button
              text
              :type="depsReady ? 'success' : 'warning'"
              @click="w.checkDeps"
              >{{
                depsReady ? "● FFmpeg" : t("检查 FFmpeg", "Check FFmpeg")
              }}</el-button
            ></el-tooltip
          ><el-select
            v-model="settings.lang"
            style="width: 110px"
            aria-label="Language"
            ><el-option value="zh" label="简体中文" /><el-option
              value="en"
              label="English" /></el-select
          ><el-button
            text
            @click="
              api('/open-url', {
                url: 'https://github.com/yibailiu/VideoMergingTool',
              })
            "
            >GitHub ↗</el-button
          >
        </div>
      </header>
      <main class="workspace">
        <div class="workspace-main">
          <section class="source-heading">
            <div>
              <div class="eyebrow">
                {{ t("视频工作区", "VIDEO WORKSPACE") }}
              </div>
              <h1>
                {{
                  t("整理视频，开始合并", "Your videos, one seamless result")
                }}
              </h1>
              <p class="source-path" :title="inputDir">
                {{
                  inputDir ||
                  t(
                    "选择文件夹，或只添加需要处理的视频",
                    "Choose a folder, or add only the videos you need",
                  )
                }}
              </p>
            </div>
            <div class="source-buttons">
              <el-button
                :icon="FolderOpened"
                :disabled="running || busy"
                @click="w.pickSource('folder')"
                >{{ t("选择文件夹", "Select folder") }}</el-button
              ><el-button
                type="primary"
                :icon="DocumentAdd"
                :disabled="running || busy"
                @click="w.pickSource('files')"
                >{{ t("选择文件", "Select files") }}</el-button
              ><el-button
                :icon="Refresh"
                :disabled="running || busy || !inputDir"
                :loading="busy"
                :aria-label="t('刷新', 'Refresh')"
                @click="w.scan()"
              />
            </div>
          </section>
          <div class="workspace-stats">
            <span
              ><i class="status-dot" :class="{ active: running }" />{{
                statusText
              }}</span
            ><span>{{ files.length }} {{ t("个视频", "videos") }}</span
            ><span>{{ ordered.length }} {{ t("个已选择", "selected") }}</span
            ><span class="policy-label"
              >{{
                settings.checkLevel === "quick"
                  ? t("快速抽检", "Quick check")
                  : settings.checkLevel === "full"
                    ? t("完整检查", "Full check")
                    : t("基础检查", "Basic check")
              }}
              ·
              {{
                settings.onError === "skip"
                  ? t("损坏时跳过", "Skip damaged inputs")
                  : t("异常时停止", "Stop on failure")
              }}</span
            >
          </div>
          <el-collapse v-if="scanIssues.length" class="scan-issues"
            ><el-collapse-item
              :title="
                t(
                  `${scanIssues.length} 个文件无法分析，开始时将按异常策略处理`,
                  `${scanIssues.length} files could not be analyzed; the failure policy will apply`,
                )
              "
              ><div v-for="issue in scanIssues" :key="issue.path" class="issue">
                <strong>{{ issue.path }}</strong>
                <p>{{ issue.reason }}</p>
                <el-button
                  link
                  type="primary"
                  :disabled="running"
                  @click="w.excludeScanIssue(issue.path)"
                  >{{
                    t("从本次任务排除", "Exclude from this task")
                  }}</el-button
                >
              </div></el-collapse-item
            ></el-collapse
          >
          <VideoTable
            :files="files"
            :selected="selected"
            :orientations="orientations"
            :rotations="rotations"
            :widths="settings.columnWidths"
            :checks="checks"
            :disabled="running || busy"
            :zh="zh"
            @toggle="w.toggle"
            @rotate="w.rotate"
            @open="w.openMedia"
            @widths="settings.columnWidths = $event"
            @select-all="selected = new Set(files.map((file) => file.path))"
            @clear="selected = new Set()"
          />
          <div v-if="plan && files.length" class="plan-summary">
            <span>{{ t("预计处理", "Processing plan") }}</span
            ><el-tag type="success" size="small"
              >{{ t("直通", "Copy") }} {{ plan.copy_count }}</el-tag
            ><el-tag size="small"
              >{{ t("封装", "Remux") }} {{ plan.remux_count }}</el-tag
            ><el-tag type="warning" size="small"
              >{{ t("音频转码", "Audio") }} {{ plan.audio_count }}</el-tag
            ><el-tag type="warning" size="small"
              >{{ t("视频转码", "Video") }} {{ plan.transcode_count }}</el-tag
            >
          </div>
          <TaskResult :result="result" :zh="zh" @retry="w.retryFailures" />
          <LogPanel
            :lines="logs"
            :zh="zh"
            :copying="copyingLogs"
            @copy="w.copyLogs"
            @view="w.showFullLogs"
          />
          <el-dialog
            v-model="logDialogVisible"
            :title="t('完整处理日志', 'Full process log')"
            width="85%"
          >
            <p>
              {{
                t(
                  "点击文本后可全选复制；此处包含全部日志，不受筛选或虚拟滚动影响。",
                  "Select and copy all text here. This includes all logs, regardless of filtering or virtual scrolling.",
                )
              }}
            </p>
            <el-input
              :model-value="fullLogText"
              type="textarea"
              readonly
              :rows="20"
              :aria-label="t('完整处理日志', 'Full process log')"
            />
            <template #footer
              ><el-button :loading="copyingLogs" @click="w.copyLogs">{{
                t("复制完整日志", "Copy full log")
              }}</el-button></template
            >
          </el-dialog>
        </div>
        <SettingsPanel
          :settings="settings"
          :disabled="running || busy"
          :zh="zh"
          @pick="w.pickDirectory"
        />
      </main>
      <footer class="task-footer">
        <div class="task-progress">
          <div>
            <span>{{ statusText }}</span
            ><strong>{{ progress }}%</strong>
          </div>
          <el-progress
            :percentage="progress"
            :show-text="false"
            :stroke-width="5"
          />
        </div>
        <div class="task-actions">
          <el-button
            v-if="running"
            size="large"
            type="danger"
            :icon="CircleClose"
            @click="w.cancel"
            >{{ t("停止任务", "Stop task") }}</el-button
          ><el-button
            v-else
            size="large"
            type="primary"
            :icon="VideoPlay"
            :disabled="
              busy || (!ordered.length && !scanIssues.length) || !depsReady
            "
            @click="w.start"
            >{{
              settings.dryRun
                ? t("试运行", "Dry run")
                : t("开始合并", "Start merge")
            }}</el-button
          >
        </div>
      </footer>
    </div>
  </el-config-provider>
</template>
