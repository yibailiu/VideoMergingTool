<script setup lang="ts">
import { computed } from "vue";
import type { TaskResult } from "../types";
const props = defineProps<{ result: TaskResult | null; zh: boolean }>();
defineEmits(["retry"]);
const title = computed(
  () =>
    ({
      completed: props.zh ? "合并完成" : "Merge completed",
      partial: props.zh ? "部分完成" : "Partially completed",
      failed: props.zh ? "任务失败" : "Task failed",
      cancelled: props.zh ? "已取消" : "Cancelled",
      running: props.zh ? "正在处理" : "Processing",
    })[props.result?.status || ""] || "",
);
</script>
<template>
  <section v-if="result && result.status !== 'running'" class="result-panel">
    <el-alert
      :title="title"
      :type="
        result.status === 'completed'
          ? 'success'
          : result.status === 'partial'
            ? 'warning'
            : 'error'
      "
      :closable="false"
      show-icon
    >
      <template #default
        ><span
          >{{ result.outputs.length }} {{ zh ? "个输出" : "outputs" }} ·
          {{ result.skipped.length }}
          {{ zh ? "个视频已跳过" : "videos skipped" }}</span
        >
        <p v-if="result.error" class="result-error">
          {{ result.error }}
        </p></template
      >
    </el-alert>
    <div v-for="output in result.outputs" :key="output" class="output-path">
      {{ output }}
    </div>
    <el-collapse v-if="result.skipped.length"
      ><el-collapse-item
        :title="zh ? '查看跳过清单与原因' : 'Review skipped files and reasons'"
      >
        <div v-for="issue in result.skipped" :key="issue.path" class="issue">
          <strong>{{ issue.path }}</strong>
          <p>{{ issue.stage }} · {{ issue.reason }}</p>
        </div>
        <el-button size="small" @click="$emit('retry')">{{
          zh ? "重新载入失败文件" : "Reload failed files"
        }}</el-button>
      </el-collapse-item></el-collapse
    >
  </section>
</template>
