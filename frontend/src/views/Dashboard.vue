<template>
  <div class="dashboard-page" v-loading="loading">
    <!-- 欢迎区域 -->
    <div class="welcome-section">
      <div class="welcome-text">
        <h2 class="pc-page-title">{{ greeting }}，{{ userStore.displayName }}</h2>
        <p>{{ $t('dashboard.welcomeBack') }}</p>
      </div>
      <el-button type="primary" size="large" @click="$router.push('/chat')">
        <el-icon><ChatDotRound /></el-icon>
        {{ $t('dashboard.chatNow') }}
      </el-button>
    </div>

    <!-- 概览指标卡片 -->
    <div class="overview-cards" :class="{ 'cols-5': userStore.isAdmin }">
      <div v-for="(card, i) in overviewCards" :key="card.key" class="overview-card" :class="card.key" :style="{ animationDelay: `${i * 0.08}s` }">
        <div class="card-icon-wrap">
          <el-icon :size="20"><component :is="card.icon" /></el-icon>
        </div>
        <div class="card-body">
          <div class="card-label">{{ card.label }}</div>
          <div class="card-value">
            <span class="primary-count">{{ card.value }}</span>
            <span v-if="card.subValue" class="sub-count">{{ card.subValue }}</span>
          </div>
        </div>
        <span class="card-badge" :class="card.badgeClass">
          {{ card.badgeText }}
        </span>
      </div>
    </div>

    <!-- 主内容区域 -->
    <div class="main-content">
      <!-- 左侧：API 用量统计 -->
      <div class="content-left">
        <el-card class="api-usage-card">
          <template #header>
            <div class="card-header">
              <span>{{ $t('dashboard.apiUsageStats') }}</span>
              <el-tag type="info" size="small">{{ $t('dashboard.realtimeUpdate') }}</el-tag>
            </div>
          </template>

          <div class="usage-stats" v-loading="loading">
            <div class="usage-item">
              <span class="usage-value primary">{{ usageStats.total_calls }}</span>
              <span class="usage-label">{{ $t('dashboard.callCount') }}</span>
            </div>
            <div class="usage-item">
              <span class="usage-value">{{ formatNumber(usageStats.input_tokens) }}</span>
              <span class="usage-label">{{ $t('dashboard.inputTokens') }}</span>
            </div>
            <div class="usage-item">
              <span class="usage-value">{{ formatNumber(usageStats.output_tokens) }}</span>
              <span class="usage-label">{{ $t('dashboard.outputTokens') }}</span>
            </div>
            <div class="usage-item">
              <span class="usage-value">{{ usageStats.avg_duration_ms.toFixed(1) }}ms</span>
              <span class="usage-label">{{ $t('dashboard.avgDuration') }}</span>
            </div>
            <div class="usage-item">
              <span class="usage-value danger">{{ usageStats.failed_calls }}</span>
              <span class="usage-label">{{ $t('dashboard.failedCount') }}</span>
            </div>
            <div class="usage-item">
              <span v-if="usageStats.total_calls === 0" class="usage-value">-</span>
              <el-progress v-else type="circle" :percentage="successRate" :width="56" :stroke-width="5" :color="successRate >= 95 ? 'var(--pc-accent-green)' : 'var(--pc-accent-orange)'" :show-text="true">
                <template #default="{ percentage }">
                  <span class="success-rate-text">{{ percentage }}%</span>
                </template>
              </el-progress>
              <span class="usage-label">{{ $t('dashboard.successRate') }}</span>
            </div>
          </div>

          <el-divider style="margin: 12px 0" />

          <div class="model-distribution">
            <h4>{{ $t('dashboard.modelDistribution') }}</h4>
            <div v-for="(data, model) in usageStats.model_distribution" :key="model" class="model-item">
              <div class="model-info">
                <span class="model-name">{{ model }}</span>
                <div class="model-bar">
                  <div class="model-bar-fill" :style="{ width: getBarWidth(data.calls) }"></div>
                </div>
              </div>
              <div class="model-stats">
                <span class="calls">{{ data.calls }} {{ $t('dashboard.times') }}</span>
                <span class="tokens">{{ formatNumber(data.tokens) }} tokens</span>
              </div>
            </div>
            <el-empty v-if="!usageStats.model_distribution || Object.keys(usageStats.model_distribution).length === 0" :description="$t('dashboard.noCallData')" :image-size="60" />
          </div>
        </el-card>
      </div>

      <!-- 右侧 -->
      <div class="content-right">
        <!-- 任务分布 -->
        <el-card class="task-dist-card">
          <template #header>
            <div class="card-header">
              <span>{{ $t('dashboard.taskDistribution') }}</span>
              <el-tag size="small" type="info">{{ $t('dashboard.today') }}</el-tag>
            </div>
          </template>
          <v-chart :option="taskPieOption" style="height: 200px" autoresize />
        </el-card>

        <!-- 模型调用趋势 -->
        <el-card class="trend-card">
          <template #header>
            <div class="card-header">
              <span>24h 调用趋势</span>
            </div>
          </template>
          <v-chart :option="trendOption" style="height: 220px" autoresize />
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { use } from 'echarts/core'
import { PieChart, BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import { api } from '@/api'
import { useUserStore } from '@/stores/user'

use([PieChart, BarChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent, CanvasRenderer])
import {
  ChatDotRound, Cpu, Connection, List, DataLine, Checked
} from '@element-plus/icons-vue'

const { t } = useI18n()
const userStore = useUserStore()
const loading = ref(true)
const refreshTimer = ref<number | null>(null)

const counts = ref({
  gateway_total: 0,
  gateway_online: 0,
  agents_online: 0,
  agents_total: 0,
  tasks_today: 0,
  tasks_today_by_status: {} as Record<string, number>,
  api_calls_today: 0,
  api_failed_today: 0,
  skills: 0,
  memories: 0,
  pending_approvals: 0,
  recent_tasks: [] as any[],
})

const usageStats = ref({
  total_calls: 0,
  total_tokens: 0,
  input_tokens: 0,
  output_tokens: 0,
  avg_duration_ms: 0,
  failed_calls: 0,
  hourly_calls: [] as { hour: string; calls: number }[],
  model_distribution: {} as Record<string, { calls: number; tokens: number }>
})

const tasksTodayRunning = computed(() => counts.value.tasks_today_by_status?.in_progress || 0)
const apiLimitReached = computed(() => false)

const successRate = computed(() => {
  const total = usageStats.value.total_calls || 0
  const failed = usageStats.value.failed_calls || 0
  if (total === 0) return 0
  return Math.round(((total - failed) / total) * 100)
})

const overviewCards = computed(() => {
  const cards = [
    {
      key: 'gateway',
      icon: Connection,
      label: t('dashboard.centerStatus'),
      value: counts.value.gateway_online > 0 ? t('dashboard.running') : t('common.offline'),
      subValue: '',
      badgeClass: counts.value.gateway_online > 0 ? 'badge-success' : 'badge-danger',
      badgeText: counts.value.gateway_online > 0 ? t('common.online') : t('common.offline'),
    },
    {
      key: 'agents',
      icon: Cpu,
      label: t('dashboard.onlineAgents'),
      value: String(counts.value.agents_online),
      subValue: `/ ${counts.value.agents_total}`,
      badgeClass: 'badge-success',
      badgeText: t('dashboard.activeCount', { count: counts.value.agents_online }),
    },
    {
      key: 'tasks',
      icon: List,
      label: t('dashboard.todayTasks'),
      value: String(counts.value.tasks_today),
      subValue: '',
      badgeClass: tasksTodayRunning.value > 0 ? 'badge-warning' : 'badge-info',
      badgeText: tasksTodayRunning.value > 0 ? t('dashboard.inProgressCount', { count: tasksTodayRunning.value }) : t('dashboard.noInProgress'),
    },
    {
      key: 'api',
      icon: DataLine,
      label: t('dashboard.apiCalls'),
      value: String(counts.value.api_calls_today),
      subValue: '',
      badgeClass: apiLimitReached.value ? 'badge-danger' : 'badge-info',
      badgeText: apiLimitReached.value ? t('dashboard.limitReached') : t('dashboard.normal'),
    },
  ]
  if (userStore.isAdmin) {
    cards.push({
      key: 'approval',
      icon: Checked,
      label: t('dashboard.pendingApprovals'),
      value: String(counts.value.pending_approvals || 0),
      subValue: '',
      badgeClass: (counts.value.pending_approvals || 0) > 0 ? 'badge-warning' : 'badge-info',
      badgeText: (counts.value.pending_approvals || 0) > 0 ? t('dashboard.needsReview') : t('dashboard.allClear'),
    })
  }
  return cards
})

const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 6) return t('dashboard.greetingEarlyMorning')
  if (hour < 9) return t('dashboard.greetingMorning')
  if (hour < 12) return t('dashboard.greetingForenoon')
  if (hour < 14) return t('dashboard.greetingNoon')
  if (hour < 17) return t('dashboard.greetingAfternoon')
  if (hour < 19) return t('dashboard.greetingEvening')
  if (hour < 22) return t('dashboard.greetingNight')
  return t('dashboard.greetingLateNight')
})

const taskSegments = computed(() => {
  const s = counts.value.tasks_today_by_status || {}
  const total = counts.value.tasks_today || 0
  const segments = [
    { key: 'done', label: t('task.done'), class: 'seg-done', count: s.done || 0 },
    { key: 'in_progress', label: t('task.inProgress'), class: 'seg-progress', count: s.in_progress || 0 },
    { key: 'todo', label: t('task.todo'), class: 'seg-todo', count: s.todo || 0 },
    { key: 'cancelled', label: t('task.cancelled'), class: 'seg-cancel', count: s.cancelled || 0 },
  ]
  return segments.map(seg => ({
    ...seg,
    percent: total > 0 ? (seg.count / total) * 100 : 0,
  }))
})

const taskPieOption = computed(() => {
  const segments = taskSegments.value
  return {
    tooltip: { trigger: 'item' as const },
    legend: { bottom: 0 },
    color: ['#10b981', '#0ea5e9', '#f59e0b', '#ef4444'],
    series: [{
      type: 'pie' as const,
      radius: ['50%', '75%'],
      center: ['50%', '45%'],
      label: { show: false },
      data: segments.map(s => ({ name: s.label, value: s.count })),
    }],
  }
})

const trendOption = computed(() => {
  const hourly = usageStats.value.hourly_calls || []
  return {
    tooltip: { trigger: 'axis' as const },
    grid: { left: 40, right: 20, top: 10, bottom: 30 },
    xAxis: {
      type: 'category' as const,
      data: hourly.map((h: any) => h.hour || ''),
      axisLabel: { fontSize: 10, color: '#94a3b8' },
    },
    yAxis: { type: 'value' as const, axisLabel: { fontSize: 10, color: '#94a3b8' } },
    series: [{
      type: 'bar' as const,
      data: hourly.map((h: any) => h.calls || 0),
      itemStyle: { color: 'rgba(14, 165, 233, 0.7)', borderRadius: [4, 4, 0, 0] },
      barWidth: '60%',
    }],
  }
})

function formatNumber(num: number): string {
  if (num >= 10000) return (num / 1000).toFixed(1) + 'K'
  return num.toString()
}

function getBarWidth(calls: number): string {
  const total = usageStats.value.total_calls || 1
  return `${(calls / total) * 100}%`
}

async function fetchData() {
  loading.value = true
  try {
    const [statsRes, countsRes] = await Promise.all([
      api.get('/dashboard/stats'),
      api.get('/dashboard/counts'),
    ])
    usageStats.value = statsRes.data
    counts.value = countsRes.data
  } catch (error) {
    console.error('Failed to fetch dashboard data:', error)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchData()
  refreshTimer.value = window.setInterval(() => {
    fetchData()
  }, 30000)
})

onUnmounted(() => {
  if (refreshTimer.value) {
    clearInterval(refreshTimer.value)
  }
})
</script>

<style scoped lang="scss">
.dashboard-page {
  animation: pc-slide-up 0.4s ease;

  /* ====== 欢迎区域 ====== */
  .welcome-section {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 28px 32px;
    background: var(--pc-gradient-surface);
    border: 1px solid var(--pc-glass-border);
    border-radius: var(--pc-radius-lg);
    margin-bottom: 20px;
    position: relative;
    overflow: hidden;

    &::before {
      content: '';
      position: absolute;
      top: 0;
      right: 0;
      width: 300px;
      height: 100%;
      background: radial-gradient(ellipse at right, rgba(var(--pc-primary-rgb), 0.06), transparent 70%);
      pointer-events: none;
    }

    .welcome-text {
      h2 {
        font-size: 22px;
        font-weight: 600;
        margin-bottom: 6px;
        background: var(--pc-gradient-primary);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        letter-spacing: -0.3px;
      }
      p {
        color: var(--pc-text-secondary);
        font-size: 13px;
      }
    }

    :deep(.el-button--primary) {
      background: var(--pc-gradient-primary) !important;
      border: none !important;
      border-radius: var(--pc-radius-md);
      padding: 10px 24px;
      font-weight: 500;
      box-shadow: 0 0 20px rgba(var(--pc-primary-rgb), 0.2);
    }
  }

  /* ====== 概览指标卡片 ====== */
  .overview-cards {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 20px;

    &.cols-5 {
      grid-template-columns: repeat(5, 1fr);
    }
  }

  .overview-card {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 20px;
    background: var(--pc-glass-bg);
    backdrop-filter: blur(var(--pc-glass-blur));
    border: 1px solid var(--pc-glass-border);
    border-radius: var(--pc-radius-lg);
    height: 96px;
    box-sizing: border-box;
    transition: all 0.3s ease;
    position: relative;
    overflow: hidden;

    &::after {
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 2px;
      background: var(--pc-gradient-primary);
      opacity: 0;
      transition: opacity 0.3s ease;
    }

    &:hover {
      border-color: var(--pc-border-hover);
      box-shadow: var(--pc-shadow-glow);
      transform: translateY(-2px);

      &::after {
        opacity: 1;
      }
    }

    .card-icon-wrap {
      width: 44px;
      height: 44px;
      border-radius: var(--pc-radius-md);
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }

    &.gateway .card-icon-wrap { background: rgba(var(--pc-primary-rgb), 0.12); color: var(--pc-primary); }
    &.agents .card-icon-wrap { background: rgba(var(--pc-accent-green-rgb), 0.12); color: var(--pc-accent-green); }
    &.tasks .card-icon-wrap { background: rgba(255, 140, 66, 0.12); color: var(--pc-accent-orange); }
    &.api .card-icon-wrap { background: rgba(var(--pc-accent-purple-rgb), 0.12); color: var(--pc-accent-purple); }
    &.approval .card-icon-wrap { background: rgba(255, 140, 66, 0.12); color: var(--pc-accent-orange); }

    .card-body {
      flex: 1;
      min-width: 0;

      .card-label {
        color: var(--pc-text-secondary);
        font-size: 12px;
        margin-bottom: 4px;
        line-height: 1;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }

      .card-value {
        line-height: 1.2;

        .primary-count {
          font-size: 24px;
          font-weight: 700;
          color: var(--pc-text-primary);
        }

        .sub-count {
          font-size: 13px;
          font-weight: 400;
          color: var(--pc-text-muted);
        }
      }
    }

    .card-badge {
      font-size: 10px;
      padding: 3px 8px;
      border-radius: 10px;
      white-space: nowrap;
      flex-shrink: 0;
      line-height: 1.4;
      font-weight: 500;
      letter-spacing: 0.3px;
      text-transform: uppercase;
    }

    .badge-success { background: rgba(var(--pc-accent-green-rgb), 0.12); color: var(--pc-accent-green); }
    .badge-danger { background: rgba(255, 77, 106, 0.12); color: var(--pc-accent-red); }
    .badge-warning { background: rgba(255, 140, 66, 0.12); color: var(--pc-accent-orange); }
    .badge-info { background: rgba(var(--pc-accent-purple-rgb), 0.12); color: var(--pc-accent-purple); }
  }

  /* ====== 主内容区域 ====== */
  .main-content {
    display: grid;
    grid-template-columns: 14fr 10fr;
    gap: 16px;

    .content-left {
      min-width: 0;

      .api-usage-card {
        height: 100%;
      }
    }

    .content-right {
      display: flex;
      flex-direction: column;
      gap: 16px;
      min-width: 0;
    }
  }

  :deep(.el-card__header) {
    padding: 14px 20px;
    border-bottom: 1px solid var(--pc-border);
  }

  :deep(.el-card__body) {
    padding: 16px 20px;
  }

  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-weight: 500;
    font-size: 14px;

    .view-all-btn {
      padding: 4px 12px !important;
      border-radius: 6px;

      &:hover {
        background: rgba(var(--pc-primary-rgb), 0.06);
      }

      .el-icon {
        margin-right: 4px;
      }
    }
  }

  /* ====== API 用量统计 ====== */
  .usage-stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
    text-align: center;

    .usage-item {
      padding: 12px 4px;
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid var(--pc-border);
      border-radius: var(--pc-radius-md);
      transition: all 0.2s;

      &:hover {
        background: rgba(var(--pc-primary-rgb), 0.04);
        border-color: var(--pc-border-hover);
      }

      .usage-value {
        display: block;
        font-size: 18px;
        font-weight: 700;
        color: var(--pc-text-primary);
        line-height: 1.3;

        &.primary { color: var(--pc-primary); }
        &.danger { color: var(--pc-accent-red); }
      }

      .usage-label {
        color: var(--pc-text-muted);
        font-size: 10px;
        display: block;
        margin-top: 4px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }

      .success-rate-text {
        font-size: 13px;
        font-weight: 700;
        color: var(--pc-text-primary);
      }
    }
  }

  .model-distribution {
    h4 {
      margin-bottom: 14px;
      font-size: 13px;
      color: var(--pc-text-primary);
      font-weight: 500;
    }

    .model-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 10px 0;
      border-bottom: 1px solid var(--pc-border);

      &:last-child { border-bottom: none; }

      .model-info {
        flex: 1;
        margin-right: 12px;

        .model-name {
          display: block;
          font-weight: 500;
          margin-bottom: 6px;
          font-size: 13px;
          color: var(--pc-text-primary);
        }

        .model-bar {
          height: 3px;
          background: rgba(255, 255, 255, 0.06);
          border-radius: 2px;
          overflow: hidden;

          .model-bar-fill {
            height: 100%;
            background: var(--pc-gradient-primary);
            border-radius: 2px;
            box-shadow: 0 0 6px rgba(var(--pc-primary-rgb), 0.3);
          }
        }
      }

      .model-stats {
        text-align: right;
        white-space: nowrap;
        font-size: 12px;

        .calls { font-weight: 600; margin-right: 6px; color: var(--pc-text-primary); }
        .tokens { color: var(--pc-text-muted); }
      }
    }
  }

  /* ====== 任务分布 ====== */
  .task-dist-card {
    .dist-bar {
      height: 8px;
      border-radius: 4px;
      background: rgba(255, 255, 255, 0.04);
      display: flex;
      overflow: hidden;
      margin-bottom: 16px;

      .dist-segment {
        height: 100%;
        transition: width 0.5s ease;

        &.seg-done { background: var(--pc-accent-green); box-shadow: 0 0 8px rgba(var(--pc-accent-green-rgb), 0.3); }
        &.seg-progress { background: var(--pc-accent-orange); }
        &.seg-todo { background: var(--pc-primary); box-shadow: 0 0 8px rgba(var(--pc-primary-rgb), 0.3); }
        &.seg-cancel { background: rgba(255, 255, 255, 0.1); }
      }
    }

    .dist-legend {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 10px;

      .legend-item {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 12px;

        .legend-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          flex-shrink: 0;

          &.seg-done { background: var(--pc-accent-green); box-shadow: 0 0 6px rgba(var(--pc-accent-green-rgb), 0.4); }
          &.seg-progress { background: var(--pc-accent-orange); }
          &.seg-todo { background: var(--pc-primary); box-shadow: 0 0 6px rgba(var(--pc-primary-rgb), 0.4); }
          &.seg-cancel { background: rgba(255, 255, 255, 0.15); }
        }

        .legend-label { color: var(--pc-text-secondary); }
        .legend-count { margin-left: auto; font-weight: 600; color: var(--pc-text-primary); }
      }
    }
  }

}

@media (max-width: 1200px) {
  .dashboard-page .overview-cards,
  .dashboard-page .overview-cards.cols-5 {
    grid-template-columns: repeat(3, 1fr);
  }
  .dashboard-page .main-content {
    grid-template-columns: 1fr;
  }
  .dashboard-page .usage-stats {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .dashboard-page .welcome-section {
    flex-direction: column;
    gap: 12px;
    text-align: center;
  }
  .dashboard-page .overview-cards,
  .dashboard-page .overview-cards.cols-5 {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 480px) {
  .dashboard-page .overview-cards,
  .dashboard-page .overview-cards.cols-5 {
    grid-template-columns: 1fr;
  }
  .dashboard-page .usage-stats {
    grid-template-columns: 1fr;

    .usage-item:last-child {
      grid-column: 1;
    }
  }
}
</style>
