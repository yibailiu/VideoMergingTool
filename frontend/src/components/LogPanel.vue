<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
const props = defineProps<{ lines: string[]; zh: boolean }>();
defineEmits(["export"]);
const viewport = ref<HTMLElement>(),
  top = ref(0),
  follow = ref(true),
  filter = ref("all");
const lineHeight = 24;
const filtered = computed(() =>
  props.lines.filter(
    (line) =>
      filter.value === "all" || /error|warning|failed|skipping/i.test(line),
  ),
);
const start = computed(() =>
  Math.max(0, Math.floor(top.value / lineHeight) - 8),
);
const visible = computed(() =>
  filtered.value.slice(start.value, start.value + 70),
);
function scroll() {
  if (viewport.value) top.value = viewport.value.scrollTop;
}
watch(
  () => [props.lines.length, filter.value],
  async () => {
    await nextTick();
    if (follow.value && viewport.value)
      viewport.value.scrollTop = viewport.value.scrollHeight;
  },
);
</script>
<template>
  <section class="log-panel">
    <div class="section-heading">
      <h3>
        {{ zh ? "处理日志" : "Process log" }}
        <span class="muted">{{ lines.length }}</span>
      </h3>
      <div class="toolbar-buttons">
        <el-select v-model="filter" size="small" style="width: 120px"
          ><el-option
            value="all"
            :label="zh ? '全部日志' : 'All logs'" /><el-option
            value="issues"
            :label="zh ? '警告与错误' : 'Warnings / errors'" /></el-select
        ><el-checkbox v-model="follow">{{
          zh ? "跟随输出" : "Follow"
        }}</el-checkbox
        ><el-button size="small" @click="$emit('export')">{{
          zh ? "导出完整日志" : "Export full log"
        }}</el-button>
      </div>
    </div>
    <div ref="viewport" class="log-viewport" role="log" @scroll="scroll">
      <div
        :style="{
          height: filtered.length * lineHeight + 'px',
          position: 'relative',
        }"
      >
        <div :style="{ transform: `translateY(${start * lineHeight}px)` }">
          <div
            v-for="(line, index) in visible"
            :key="start + index"
            class="log-line"
            :class="{
              'log-error': /error|failed/i.test(line),
              'log-warning': /warning|skipping/i.test(line),
            }"
            :title="line"
          >
            {{ line }}
          </div>
        </div>
      </div>
      <div v-if="!lines.length" class="empty-log">
        {{
          zh
            ? "任务开始后，这里会显示检查与合并记录。"
            : "Checks and merge activity will appear here."
        }}
      </div>
    </div>
  </section>
</template>
