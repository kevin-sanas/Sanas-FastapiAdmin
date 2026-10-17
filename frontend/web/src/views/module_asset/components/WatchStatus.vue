<template>
  <ElCard class="watch-panel" shadow="hover" aria-labelledby="watch-title">
    <template #header>
      <div class="watch-heading">
        <div>
          <h2 id="watch-title">AssetFlow 后端运行</h2>
          <p class="asset-muted">由 Sanas Watch 探测服务接口 · 每 15 秒同步</p>
        </div>
        <ElButton :loading="loading" @click="load"
          ><FaSvgIcon icon="ri:refresh-line" />刷新状态</ElButton
        >
      </div>
    </template>
    <div class="watch-scope">
      <FaSvgIcon icon="ri:information-line" />
      <span>监测资产系统后端，不代表实物资产是否在线。</span>
      <ElTooltip placement="top" content="存活：接口能响应；就绪：数据库及已启用的 Redis 可连接。">
        <span class="watch-help" tabindex="0">指标说明</span>
      </ElTooltip>
    </div>
    <div aria-live="polite">
      <ElSkeleton v-if="loading && !snapshot && !failed" :rows="2" animated />
      <ElAlert
        v-else-if="failed || snapshot?.state === 'unavailable'"
        title="暂时无法获取监控状态"
        description="运行监控暂不可用，请稍后刷新。资产查询与审批可继续使用。"
        type="warning"
        :closable="false"
        show-icon
      />
      <p
        v-else-if="snapshot?.state === 'disabled' || snapshot?.state === 'not_configured'"
        class="asset-muted"
      >
        尚未接入运行监控，请联系管理员配置。
      </p>
      <template v-else-if="snapshot">
        <ElAlert
          v-if="snapshot.state === 'stale'"
          title="监控连接中断，以下为上次读取的状态"
          description="旧数据最多保留 5 分钟，不能作为当前服务正常的依据。"
          type="warning"
          :closable="false"
          show-icon
        />
        <ul class="watch-list">
          <li v-for="monitor in snapshot.monitors" :key="monitor.id" class="watch-row">
            <div class="watch-service">
              <span class="asset-name">{{ monitor.name }}</span>
              <ElTag :type="statuses[monitor.status].color" effect="plain">
                {{ snapshot.state === "stale" ? "上次：" : "" }}{{ statuses[monitor.status].text }}
              </ElTag>
            </div>
            <dl class="watch-metrics">
              <div>
                <dt>最近一次探测耗时</dt>
                <dd>{{ metric(monitor.response_ms, "ms") }}</dd>
              </div>
              <div>
                <dt>近 24 小时在线率</dt>
                <dd>{{ metric(monitor.uptime_24h_percent, "%") }}</dd>
              </div>
            </dl>
          </li>
        </ul>
        <p class="asset-muted watch-time">
          状态同步于 {{ fetchedTime }} · 在线率只按已观测时段计算。
        </p>
      </template>
    </div>
  </ElCard>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { AssetAPI, type WatchSnapshot } from "@/api/module_asset/asset";

const snapshot = ref<WatchSnapshot>();
const loading = ref(false);
const failed = ref(false);
let disposed = false;
let timer: ReturnType<typeof setInterval> | undefined;
const statuses = {
  up: { text: "正常", color: "success" },
  down: { text: "故障", color: "danger" },
  pending: { text: "重试中", color: "warning" },
  maintenance: { text: "维护中", color: "info" },
  unknown: { text: "暂无采样", color: "info" },
} as const;
const fetchedTime = computed(() =>
  snapshot.value?.fetched_at ? new Date(snapshot.value.fetched_at).toLocaleString() : "—"
);
function metric(value: number | null, unit: string) {
  return value === null
    ? "—"
    : `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${unit}`;
}
async function load() {
  if (loading.value || disposed) return;
  loading.value = true;
  try {
    const result = await AssetAPI.monitoring();
    if (!disposed) {
      snapshot.value = result;
      failed.value = false;
    }
  } catch {
    if (!disposed) {
      snapshot.value = undefined;
      failed.value = true;
    }
  } finally {
    if (!disposed) loading.value = false;
  }
}
onMounted(() => {
  void load();
  timer = setInterval(() => {
    if (!document.hidden) void load();
  }, 15_000);
});
onBeforeUnmount(() => {
  disposed = true;
  if (timer) clearInterval(timer);
});
</script>

<style scoped lang="scss">
.watch-panel {
  margin-top: 12px;
}

.watch-panel :deep(.el-card__header) {
  padding: 16px 20px;
}

.watch-heading {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;

  h2 {
    margin: 0;
    font-size: 16px;
  }

  p {
    margin-top: 4px;
  }
}

.watch-scope {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  padding-bottom: 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.watch-help {
  color: var(--el-color-primary);
  cursor: help;
}

.watch-list {
  padding: 0;
  margin: 0;
  list-style: none;
}

.watch-row {
  display: flex;
  gap: 20px;
  align-items: center;
  justify-content: space-between;
  padding: 14px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.watch-service {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  min-width: 0;
  overflow-wrap: anywhere;
}

.watch-metrics {
  display: flex;
  flex-shrink: 0;
  gap: 24px;
  margin: 0;
  text-align: right;

  dt {
    margin-bottom: 6px;
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }

  dd {
    margin: 0;
    font-variant-numeric: tabular-nums;
    color: var(--el-text-color-primary);
  }
}

.watch-time {
  margin-top: 16px;
}

@media (width <= 640px) {
  .watch-heading,
  .watch-row {
    align-items: flex-start;
  }

  .watch-row {
    flex-direction: column;
    gap: 14px;
  }

  .watch-metrics {
    flex-wrap: wrap;
    text-align: left;
  }
}
</style>
