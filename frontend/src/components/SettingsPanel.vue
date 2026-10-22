<script setup lang="ts">
import type { Settings } from "../types";
const props = defineProps<{
  settings: Settings;
  disabled: boolean;
  zh: boolean;
}>();
defineEmits(["pick"]);
const t = (cn: string, en: string) => (props.zh ? cn : en);
const sorts = [
  ["name-natural-asc", "文件名自然升序", "Natural name ↑"],
  ["name-natural-desc", "文件名自然降序", "Natural name ↓"],
  ["name-asc", "文件名文本升序", "Name ↑"],
  ["name-desc", "文件名文本降序", "Name ↓"],
  ["media-created-asc", "媒体日期从旧到新", "Media date ↑"],
  ["media-created-desc", "媒体日期从新到旧", "Media date ↓"],
  ["size-asc", "文件大小从小到大", "Size ↑"],
  ["size-desc", "文件大小从大到小", "Size ↓"],
];
</script>
<template>
  <aside class="settings-panel">
    <div class="section-heading">
      <h2>{{ t("合并设置", "Merge settings") }}</h2>
      <span class="eyebrow">{{ t("本地处理", "LOCAL PROCESSING") }}</span>
    </div>
    <el-form label-position="top" :disabled="disabled">
      <el-form-item :label="t('合并模式', 'Merge mode')">
        <div class="mode-options">
          <button
            v-for="mode in [
              {
                id: 'fast',
                cn: '快速合并',
                en: 'Fast',
                desc: t(
                  '直接复制兼容音视频，不转码',
                  'Copy compatible streams without encoding',
                ),
              },
              {
                id: 'optimal',
                cn: '智能合并',
                en: 'Optimal',
                desc: t(
                  '按方向生成结果，仅在必要时转码',
                  'Separate orientation outputs; encode only when needed',
                ),
              },
              {
                id: 'extreme',
                cn: '强制合并',
                en: 'Extreme',
                desc: t(
                  '统一画面规格，合并为一个结果',
                  'Normalize into one output',
                ),
              },
            ]"
            :key="mode.id"
            type="button"
            class="mode-option"
            :class="{ active: settings.mode === mode.id }"
            :disabled="disabled"
            @click="settings.mode = mode.id"
          >
            <strong>{{ zh ? mode.cn : mode.en }}</strong
            ><small>{{ mode.desc }}</small>
          </button>
        </div>
      </el-form-item>
      <div class="settings-section">
        <h3>{{ t("检查与异常处理", "Checks & failure handling") }}</h3>
        <el-form-item :label="t('开始前检查', 'Check before merging')"
          ><el-select v-model="settings.checkLevel"
            ><el-option
              value="basic"
              :label="
                t('基础检查 · 仅读取参数', 'Basic · metadata only')
              " /><el-option
              value="quick"
              :label="
                t('快速抽检 · 开头、中间、结尾', 'Quick · start, middle, end')
              " /><el-option
              value="full"
              :label="
                t('完整解码检查 · 耗时更长', 'Full decode · takes longer')
              " /></el-select
        ></el-form-item>
        <p class="field-hint">
          {{
            t(
              "快速抽检无法保证未抽取部分没有损坏。检查超时或无法确定时将停止任务。",
              "Sampling cannot guarantee unsampled content. An inconclusive or timed-out check stops the task.",
            )
          }}
        </p>
        <el-form-item :label="t('遇到损坏视频', 'If an input is damaged')"
          ><el-select v-model="settings.onError"
            ><el-option
              value="stop"
              :label="t('立即结束任务', 'Stop immediately')" /><el-option
              value="skip"
              :label="
                t('跳过该视频并继续', 'Skip this video and continue')
              " /></el-select
        ></el-form-item>
      </div>
      <div class="settings-section">
        <h3>{{ t("输出", "Output") }}</h3>
        <el-form-item :label="t('文件名前缀', 'Filename prefix')"
          ><el-input v-model="settings.name" placeholder="Merged_Output"
        /></el-form-item>
        <el-form-item :label="t('输出目录', 'Output folder')"
          ><el-input
            v-model="settings.outputDir"
            :placeholder="
              t('默认：源目录 / merged', 'Default: source / merged')
            "
            ><template #append
              ><el-button @click="$emit('pick', 'outputDir')">{{
                t("浏览", "Browse")
              }}</el-button></template
            ></el-input
          ></el-form-item
        >
        <div class="form-pair">
          <el-form-item :label="t('输出格式', 'Format')"
            ><el-select v-model="settings.format"
              ><el-option
                v-for="format in ['mp4', 'mkv', 'mov', 'avi', 'ts', 'webm']"
                :key="format"
                :value="format"
                :label="format.toUpperCase()" /></el-select></el-form-item
          ><el-form-item :label="t('质量策略', 'Quality')"
            ><el-select
              v-model="settings.qualityProfile"
              @change="
                (value: string) => {
                  settings.crf =
                    value === 'high' ? 20 : value === 'small' ? 25 : 23;
                  settings.preset = value === 'high' ? 'slow' : 'medium';
                }
              "
              ><el-option
                value="balanced"
                :label="t('均衡', 'Balanced')" /><el-option
                value="high"
                :label="t('高质量', 'High quality')" /><el-option
                value="small"
                :label="t('较小体积', 'Smaller file')" /></el-select
          ></el-form-item>
        </div>
        <el-form-item :label="t('全局合并顺序', 'Global merge order')"
          ><el-select v-model="settings.sortBy"
            ><el-option
              v-for="sort in sorts"
              :key="sort[0]"
              :value="sort[0]"
              :label="zh ? sort[1] : sort[2]" /></el-select
        ></el-form-item>
        <el-form-item :label="t('GPU 加速', 'GPU acceleration')"
          ><el-select v-model="settings.gpu"
            ><el-option
              v-for="gpu in [
                'off',
                'auto',
                'nvenc',
                'qsv',
                'amf',
                'videotoolbox',
              ]"
              :key="gpu"
              :value="gpu"
              :label="
                gpu === 'off'
                  ? t('关闭 · CPU', 'Off · CPU')
                  : gpu === 'auto'
                    ? t('自动选择', 'Automatic')
                    : gpu
              " /></el-select
        ></el-form-item>
      </div>
      <el-collapse
        ><el-collapse-item
          name="advanced"
          :title="t('高级设置', 'Advanced settings')"
        >
          <el-form-item :label="t('临时目录', 'Temporary folder')"
            ><el-input
              v-model="settings.tempDir"
              :placeholder="t('系统默认', 'System default')"
              ><template #append
                ><el-button @click="$emit('pick', 'tempDir')">{{
                  t("浏览", "Browse")
                }}</el-button></template
              ></el-input
            ></el-form-item
          >
          <div class="form-pair">
            <el-form-item :label="t('视频编码', 'Video codec')"
              ><el-select v-model="settings.codec"
                ><el-option value="" :label="t('自动', 'Auto')" /><el-option
                  v-for="codec in ['h264', 'hevc', 'vp9', 'av1', 'mpeg4']"
                  :key="codec"
                  :value="codec"
                  :label="codec" /></el-select></el-form-item
            ><el-form-item :label="t('音频编码', 'Audio codec')"
              ><el-select v-model="settings.audioCodec"
                ><el-option value="" :label="t('自动', 'Auto')" /><el-option
                  v-for="codec in ['aac', 'mp3', 'opus', 'vorbis', 'pcm_s16le']"
                  :key="codec"
                  :value="codec"
                  :label="codec" /></el-select
            ></el-form-item>
          </div>
          <div class="form-pair">
            <el-form-item label="CRF"
              ><el-input-number
                v-model="settings.crf"
                :min="0"
                :max="51"
                controls-position="right" /></el-form-item
            ><el-form-item :label="t('GPU 并发数', 'GPU workers')"
              ><el-input-number
                v-model="settings.gpuWorkers"
                :min="1"
                :max="3"
                controls-position="right"
            /></el-form-item>
          </div>
          <el-form-item :label="t('编码预设', 'Encoder preset')"
            ><el-select v-model="settings.preset"
              ><el-option
                v-for="preset in [
                  'ultrafast',
                  'superfast',
                  'veryfast',
                  'faster',
                  'fast',
                  'medium',
                  'slow',
                  'slower',
                  'veryslow',
                ]"
                :key="preset"
                :value="preset"
                :label="preset" /></el-select
          ></el-form-item>
          <el-form-item :label="t('帧率策略', 'Frame rate')"
            ><el-select v-model="settings.fpsPolicy"
              ><el-option
                value="majority"
                :label="t('主流源帧率', 'Dominant source')" /><el-option
                value="max"
                :label="t('最高帧率', 'Highest')" /><el-option
                value="min"
                :label="t('最低帧率', 'Lowest')" /></el-select
          ></el-form-item>
          <el-form-item :label="t('分辨率策略', 'Resolution')"
            ><el-select v-model="settings.resolutionPolicy"
              ><el-option
                value="dominant"
                :label="t('主流源规格', 'Dominant source')" /><el-option
                value="largest"
                :label="t('最大画布', 'Largest canvas')" /></el-select
          ></el-form-item>
          <el-form-item :label="t('填充颜色', 'Padding color')"
            ><el-input v-model="settings.padColor"
          /></el-form-item>
          <el-form-item :label="t('FFmpeg 路径', 'FFmpeg path')"
            ><el-input
              v-model="settings.ffmpegPath"
              :placeholder="t('自动检测', 'Automatic')"
          /></el-form-item>
          <el-form-item :label="t('FFprobe 路径', 'FFprobe path')"
            ><el-input
              v-model="settings.ffprobePath"
              :placeholder="t('自动检测', 'Automatic')"
          /></el-form-item>
          <div class="switch-list">
            <el-checkbox v-model="settings.recursive">{{
              t("递归扫描子目录", "Scan subfolders")
            }}</el-checkbox
            ><el-checkbox v-model="settings.overwrite">{{
              t("允许覆盖输出", "Overwrite outputs")
            }}</el-checkbox
            ><el-checkbox v-model="settings.keepTemp">{{
              t("保留临时文件", "Keep temporary files")
            }}</el-checkbox
            ><el-checkbox v-model="settings.dryRun">{{
              t("试运行（不执行处理）", "Dry run (no processing)")
            }}</el-checkbox
            ><el-checkbox v-model="settings.autoDownloadDeps">{{
              t("自动下载依赖", "Download dependencies automatically")
            }}</el-checkbox>
          </div> </el-collapse-item
        ><el-collapse-item :title="t('完成提醒', 'Completion notification')"
          ><div class="switch-list">
            <el-checkbox v-model="settings.notifyOnComplete">{{
              t("系统通知", "System notification")
            }}</el-checkbox
            ><el-checkbox v-model="settings.playSoundOnComplete">{{
              t("提示音", "Sound")
            }}</el-checkbox>
          </div></el-collapse-item
        ></el-collapse
      >
    </el-form>
  </aside>
</template>
