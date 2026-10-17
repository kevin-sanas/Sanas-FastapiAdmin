<template>
  <section class="asset-page" :class="`asset-page--${variant}`" :aria-label="title">
    <header v-if="variant === 'overview'" class="asset-page-heading">
      <div>
        <h1>{{ title }}</h1>
        <p>{{ description }}</p>
      </div>
      <div class="asset-actions"><slot name="actions" /></div>
    </header>
    <slot />
  </section>
</template>
<script setup lang="ts">
withDefaults(defineProps<{ title: string; description: string; variant?: "list" | "overview" }>(), {
  variant: "list",
});
</script>
<style lang="scss">
.asset-page {
  min-width: 0;
  padding: 0 0 24px;

  &.asset-page--list {
    display: flex;
    flex-direction: column;
    min-height: 100%;
  }

  .asset-page-heading {
    display: flex;
    gap: 20px;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
  }

  h1 {
    margin: 0 0 8px;
    font-size: 24px;
    font-weight: 650;
    color: var(--el-text-color-primary);
  }

  .asset-page-heading p,
  .asset-muted {
    margin: 0;
    font-size: 13px;
    line-height: 1.7;
    color: var(--el-text-color-secondary);
  }

  .asset-actions,
  .asset-toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: center;
  }

  .asset-actions .el-button + .el-button {
    margin-left: 0;
  }

  .asset-toolbar {
    margin-bottom: 0;
  }

  .asset-panel {
    padding: 20px;
    background: var(--el-bg-color);
    border: 1px solid var(--fa-card-border);
    border-radius: calc(var(--custom-radius) / 2 + 2px);
  }

  .asset-panel + .asset-panel {
    margin-top: 12px;
  }

  .asset-panel-title {
    display: flex;
    gap: 12px;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
  }

  h2 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }

  .asset-pagination {
    display: flex;
    justify-content: center;
    padding-top: 16px;
    margin-top: auto;
    overflow-x: auto;
    border-top: 1px solid var(--el-border-color-lighter);
  }

  .asset-search {
    margin-bottom: 12px;
  }

  .asset-table-card {
    flex: 1;
    min-height: 360px;
    margin-top: 0;
  }

  .asset-table-card .el-card__body {
    gap: 14px;
  }

  .asset-table-card .el-table {
    flex: 1;
  }

  .asset-table-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }

  .asset-table-actions .el-button + .el-button {
    margin-left: 0;
  }

  .asset-row-actions {
    display: flex;
    gap: 4px;
    align-items: center;
  }

  .asset-row-actions .el-button + .el-button {
    margin-left: 0;
  }

  .asset-icon-action.el-button {
    width: 30px;
    height: 30px;
    padding: 0;
    color: var(--el-color-primary);
    background: var(--el-fill-color-light);
    border: 0;
    border-radius: 5px;
  }

  .asset-icon-action.el-button--danger {
    color: var(--el-color-danger);
  }

  .asset-icon-action.el-button--warning {
    color: var(--el-color-warning);
  }

  .asset-icon-action.el-button:hover {
    background: var(--el-fill-color);
  }

  .asset-name {
    font-weight: 550;
    color: var(--el-text-color-primary);
  }

  .asset-error {
    margin-bottom: 16px;
  }

  .asset-form .el-select,
  .asset-form .el-input-number,
  .asset-form .el-date-editor {
    width: 100%;
  }

  .asset-dialog-note {
    margin: 0 0 20px;
    font-size: 13px;
    line-height: 1.7;
    color: var(--el-text-color-secondary);
  }

  .asset-detail-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 22px;
    margin: 24px 0;
  }

  .asset-detail-grid dt {
    margin-bottom: 8px;
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }

  .asset-detail-grid dd {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .asset-code {
    font-variant-numeric: tabular-nums;
  }
}

.asset-modal {
  .asset-detail-head {
    margin-bottom: 20px;
  }

  .asset-detail-head h2 {
    margin: 0 0 4px;
    font-size: 18px;
  }

  .asset-detail-audit {
    margin-top: 20px;
  }

  .asset-form .el-select,
  .asset-form .el-input-number,
  .asset-form .el-date-editor {
    width: 100%;
  }

  .asset-dialog-note,
  .asset-muted {
    font-size: 13px;
    line-height: 1.7;
    color: var(--el-text-color-secondary);
  }

  .asset-dialog-note {
    margin: 0 0 20px;
  }

  .asset-detail-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 22px;
    margin: 24px 0;
  }

  .asset-detail-grid dt {
    margin-bottom: 8px;
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }

  .asset-detail-grid dd {
    margin: 0;
    overflow-wrap: anywhere;
  }
}
@media (width <= 640px) {
  .asset-page {
    .asset-page-heading {
      flex-direction: column;
      gap: 14px;
      align-items: flex-start;
      margin-bottom: 18px;
    }

    h1 {
      font-size: 21px;
    }

    .asset-panel {
      padding: 14px;
    }

    .asset-toolbar > .el-input,
    .asset-toolbar > .el-select {
      width: 100% !important;
    }

    .asset-pagination {
      justify-content: flex-start;
    }
  }
}
</style>
