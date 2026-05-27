<template>
  <div class="skill-eval-page">
    <div class="pc-page-header">
      <h2 class="pc-page-title">{{ $t('skillEval.title') }}</h2>
      <div class="header-actions">
        <button class="pc-glow-btn primary" @click="runEvaluation" :disabled="!selectedSkill || evaluating">
          <el-icon v-if="evaluating"><Loading /></el-icon>
          <el-icon v-else><MagicStick /></el-icon>
          {{ evaluating ? '评估中...' : $t('skillEval.evaluate') }}
        </button>
        <button class="pc-glow-btn secondary" @click="downloadReport" :disabled="!evaluation || llmEvaluating">
          <el-icon><Download /></el-icon>
          下载报告
        </button>
      </div>
    </div>

    <div class="eval-container">
      <!-- ===== LEFT PANEL ===== -->
      <div class="left-panel">
        <div class="skill-selector">
          <el-select
            v-model="selectedSkillName"
            filterable
            :placeholder="$t('skillEval.selectSkill')"
            @change="onSkillChange"
            style="width: 100%"
            :loading="loadingSkills"
          >
            <el-option
              v-for="s in skills"
              :key="s.name"
              :label="s.display_name || s.name"
              :value="s.name"
            >
              <div class="skill-option">
                <span class="skill-option-name">{{ s.display_name || s.name }}</span>
                <el-tag size="small" :type="s.source === 'db' ? 'primary' : 'success'">
                  {{ s.source === 'db' ? 'DB' : 'File' }}
                </el-tag>
                <el-tag v-if="s.scope" size="small" type="info" class="scope-tag">
                  {{ getScopeLabel(s.scope) }}
                </el-tag>
              </div>
            </el-option>
          </el-select>
        </div>

        <div class="file-tree-panel">
          <div class="panel-label">
            <el-icon><FolderOpened /></el-icon>
            <span>文件</span>
          </div>
          <el-tree
            :data="fileTree"
            :props="treeProps"
            node-key="path"
            :current-node-key="activeFile"
            highlight-current
            default-expand-all
            @node-click="onFileClick"
          >
            <template #default="{ data }">
              <span class="tree-node">
                <el-icon :size="14">
                  <Document v-if="data.type === 'file'" />
                  <Folder v-else />
                </el-icon>
                <span class="tree-node-name">{{ data.name }}</span>
                <span v-if="data.size" class="tree-node-size">{{ formatSize(data.size) }}</span>
              </span>
            </template>
          </el-tree>
        </div>

        <div class="file-content-panel">
          <div class="panel-label">
            <el-icon><Memo /></el-icon>
            <span>{{ activeFile || 'SKILL.md' }}</span>
            <button v-if="fileContent" class="copy-btn" @click="copyContent" :title="$t('common.copy')">
              <el-icon :size="14"><CopyDocument /></el-icon>
            </button>
          </div>
          <div class="content-viewer" v-if="fileContent">
            <div class="markdown-body" v-html="renderedContent"></div>
          </div>
          <div class="content-empty" v-else-if="selectedSkill">
            <el-icon :size="36"><Warning /></el-icon>
            <span>选择文件查看内容</span>
          </div>
          <div class="content-empty" v-else>
            <el-icon :size="36"><Document /></el-icon>
            <span>{{ $t('skillEval.selectSkillHint') }}</span>
          </div>
        </div>
      </div>

      <!-- ===== RIGHT PANEL ===== -->
      <div class="right-panel">
        <el-tabs v-if="evaluation" v-model="activeTab" class="eval-tabs">
          <el-tab-pane label="评估" name="evaluate">
          <!-- ===== Overall Score ===== -->
          <div class="overall-card">
            <div class="score-ring">
              <svg viewBox="0 0 120 120">
                <defs>
                  <linearGradient id="scoreGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" :stop-color="scoreColor(evaluation.overall_score, llmEvaluating || evaluation.llm_pending)" />
                    <stop offset="100%" :stop-color="scoreGlowColor(evaluation.overall_score, llmEvaluating || evaluation.llm_pending)" />
                  </linearGradient>
                  <filter id="ringGlow">
                    <feGaussianBlur in="SourceGraphic" stdDeviation="2" />
                  </filter>
                </defs>
                <circle cx="60" cy="60" r="50" fill="none"
                  stroke="var(--pc-border)" stroke-width="7" opacity="0.3" />
                <circle cx="60" cy="60" r="50" fill="none"
                  :stroke="(llmEvaluating || evaluation.llm_pending) ? 'var(--pc-border)' : 'url(#scoreGradient)'" stroke-width="7"
                  stroke-linecap="round"
                  :stroke-dasharray="circumference"
                  :stroke-dashoffset="dashOffset"
                  transform="rotate(-90 60 60)"
                  filter="url(#ringGlow)" />
              </svg>
              <div class="ring-center">
                <template v-if="llmEvaluating || evaluation.llm_pending">
                  <span class="ring-value" style="color: var(--pc-text-muted)">--</span>
                </template>
                <template v-else>
                  <span class="ring-value" :style="{ color: scoreColor(evaluation.overall_score) }">{{ evaluation.overall_score }}</span>
                </template>
                <span class="ring-unit">/100</span>
              </div>
            </div>
            <div class="overall-info">
              <div class="overall-title">综合评分</div>
              <div class="overall-summary">{{ evaluation.summary }}</div>
            </div>
          </div>

          <!-- ===== Safety Rules Table ===== -->
          <div class="dashboard-card">
            <el-collapse v-model="safetyCollapse">
              <el-collapse-item name="safety">
                <template #title>
                  <div class="collapse-title">
                    <span>🛡️ 安全红线扫描</span>
                    <span class="collapse-sub">{{ evaluation.safety_hits > 0 ? `命中 ${evaluation.safety_hits}/14` : '全部通过' }}</span>
                    <span class="collapse-score" :class="evaluation.safety_score < 100 ? 'bad' : 'good'">{{ evaluation.safety_score }}/100</span>
                  </div>
                </template>
                <div class="rules-table">
                  <div
                    v-for="rule in evaluation.safety_rules"
                    :key="rule.rule_id"
                    class="rule-row"
                    :class="{ 'row-fail': !rule.passed }"
                  >
                    <div class="rule-top">
                      <span class="rule-status" :class="rule.passed ? 'pass' : 'fail'">{{ rule.passed ? '✓' : '✕' }}</span>
                      <code class="rule-id">{{ rule.rule_id }}</code>
                      <span class="rule-desc">{{ rule.description }}</span>
                      <span class="rule-severity" :class="rule.severity === 'CRITICAL' ? 'critical' : 'high'">
                        {{ rule.severity }}
                      </span>
                    </div>
                    <div v-if="!rule.passed" class="rule-detail">
                      Line {{ rule.line }}: <code>{{ rule.snippet }}</code>
                    </div>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>

          <!-- ===== Structure Checks ===== -->
          <div class="dashboard-card">
            <el-collapse v-model="structureCollapse">
              <el-collapse-item name="structure">
                <template #title>
                  <div class="collapse-title">
                    <span>🏗️ 结构规范</span>
                    <span class="collapse-score" :class="evaluation.structure_score >= 80 ? 'good' : 'bad'">{{ evaluation.structure_score }}/100</span>
                  </div>
                </template>
                <div class="checks-list">
                  <div
                    v-for="check in evaluation.structure_checks"
                    :key="check.check"
                    class="check-row"
                  >
                    <span class="check-status" :class="check.passed ? 'pass' : 'fail'">{{ check.passed ? '✓' : '✕' }}</span>
                    <span class="check-name">{{ check.check }}</span>
                    <span class="check-detail">{{ check.detail }}</span>
                    <span class="check-points" :class="check.passed ? 'got' : 'miss'">{{ check.score }}/{{ check.max_score }}</span>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>

          <!-- ===== LLM Dimensions ===== -->
          <div class="dashboard-card">
            <el-collapse v-model="llmCollapse">
              <el-collapse-item name="llm">
                <template #title>
                  <div class="collapse-title">
                    <span>LLM 深度评估</span>
                    <span v-if="llmEvaluating || evaluation.llm_pending" class="collapse-sub">
                      <el-icon class="is-loading"><Loading /></el-icon> 评估中...
                    </span>
                    <span class="collapse-score" :class="llmAvgScore >= 60 ? 'good' : 'bad'">{{ llmAvgScore }}/100</span>
                  </div>
                </template>
                <div class="dim-grid" v-if="evaluation.llm_dimensions?.length">
                  <div v-for="dim in evaluation.llm_dimensions" :key="dim.key" class="dim-card">
                    <div class="dim-top">
                      <span class="dim-label">{{ dimLabelMap[dim.key] || dim.key }}</span>
                      <span class="dim-score" :style="{ color: scoreColor(dim.score) }">{{ dim.score }}</span>
                    </div>
                    <div class="dim-bar-bg">
                      <div class="dim-bar-fill" :style="{ width: dim.score + '%', background: scoreColor(dim.score) }"></div>
                    </div>
                    <div class="dim-comment">{{ dim.comment }}</div>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>

          <!-- 修改建议 -->
          <div class="suggestions-section" v-if="evaluation?.suggestions?.length" style="margin-top:14px">
            <div class="section-title">修改建议</div>
            <div class="suggestion-list">
              <div class="suggestion-item" v-for="(sg, i) in evaluation.suggestions" :key="i">
                <span class="sg-index">{{ i + 1 }}</span>
                <div class="sg-body">
                  <div class="sg-title">{{ sg.title }}</div>
                  <div class="sg-detail" v-if="sg.detail">{{ sg.detail }}</div>
                </div>
                <el-tag :type="sg.severity === 'high' ? 'danger' : sg.severity === 'medium' ? 'warning' : 'info'" size="small" effect="dark">
                  {{ sg.severity === 'high' ? '高' : sg.severity === 'medium' ? '中' : '低' }}
                </el-tag>
              </div>
            </div>
          </div>
          </el-tab-pane>

          <!-- ===== TAB 2: Benchmark ===== -->
          <el-tab-pane label="Benchmark" name="benchmark">
            <div class="bm-page">
              <!-- ═══ PHASE 1: Setup ═══ -->
              <div class="bm-phase" v-if="!benchmarkResult">
                <div class="bm-phase-header">
                  <span class="bm-phase-title">测试用例编辑</span>
                  <button class="pc-glow-btn primary" @click="generateTestPrompts" :disabled="!selectedSkill || benchmarking" style="font-size:12px;padding:5px 14px">
                    <el-icon v-if="generatingPrompts"><Loading /></el-icon>
                    <el-icon v-else><MagicStick /></el-icon>
                    {{ generatingPrompts ? '生成中...' : 'AI 生成 Prompt' }}
                  </button>
                </div>

                <div class="bm-hint" v-if="!hasPrompts">基于 SKILL.md 自动生成测试用例和断言，也可手动输入</div>

                <div class="bm-cases" v-if="hasPrompts">
                  <div v-for="(ev, idx) in generatedEvals" :key="idx" class="bm-case-card">
                    <div class="bm-case-head">
                      <span class="bm-case-num">{{ (idx as number) + 1 }}</span>
                      <span class="bm-case-label">测试用例</span>
                      <el-button v-if="generatedEvals.length > 1 && !benchmarking" :icon="Close" circle size="small" text @click="removePrompt(idx)" />
                    </div>
                    <div class="bm-case-body">
                      <el-input v-model="ev.prompt" placeholder="用户会说的话，如 '打开B站'" :disabled="benchmarking" type="textarea" :rows="2" />
                      <el-input v-model="ev.expected" placeholder="期望输出，如 '通过CDP打开bilibili.com首页'" :disabled="benchmarking" size="small" class="bm-case-expected" />
                      <!-- Assertions -->
                      <div class="bm-case-assertions">
                        <div class="bm-assert-head">
                          <span class="bm-assert-badge">断言 {{ ev.assertions.length }}</span>
                          <el-button v-if="!benchmarking" :icon="Plus" size="small" text @click="addAssertion(idx)">添加</el-button>
                        </div>
                        <div v-for="(a, ai) in ev.assertions" :key="ai" class="bm-assert-row">
                          <el-input v-model="a.text" placeholder="关键词" :disabled="benchmarking" size="small" class="bm-assert-text" />
                          <el-input v-model="a.description" placeholder="为什么能验证" :disabled="benchmarking" size="small" class="bm-assert-desc" />
                          <el-button v-if="!benchmarking" :icon="Close" circle size="small" text @click="removeAssertion(idx, ai)" />
                        </div>
                      </div>
                    </div>
                  </div>
                  <div class="bm-actions">
                    <el-button @click="addPrompt()" :disabled="generatedEvals.length >= 5 || benchmarking" :icon="Plus">添加用例</el-button>
                    <button class="pc-glow-btn primary" @click="runBenchmark" :disabled="!hasPrompts || benchmarking" style="font-size:14px;padding:8px 24px">
                      <el-icon v-if="benchmarking" class="is-loading"><Loading /></el-icon>
                      {{ benchmarking ? '运行中...' : '运行 Benchmark' }}
                    </button>
                  </div>
                </div>

                <div v-if="benchmarking" class="bm-progress">
                  <el-icon class="is-loading"><Loading /></el-icon> 运行中... {{ streamResults.length }}/{{ activePromptCount }}
                  <el-progress :percentage="benchmarkPercent" :show-text="false" :stroke-width="2" color="var(--pc-primary)" style="flex:1;min-width:80px" />
                </div>
              </div>

              <!-- ═══ PHASE 2: Results ═══ -->
              <div class="bm-phase" v-if="benchmarkResult">
                <div class="bm-phase-header">
                  <span class="bm-phase-title">实测结果</span>
                  <el-button size="small" text @click="benchmarkResult = null; streamResults = []">← 返回编辑</el-button>
                </div>

                <!-- Per-case grading cards -->
                <div class="bm-results" v-if="benchmarkResult.runs?.length">
                  <div v-for="(run, idx) in benchmarkResult.runs" :key="idx" class="bm-result-card">
                    <div class="bm-result-head">
                      <span class="bm-case-num">{{ (idx as number) + 1 }}</span>
                      <span class="bm-result-prompt">{{ run.prompt }}</span>
                    </div>
                    <table class="bm-grade-table" v-if="run.with_assertions?.length || run.baseline_assertions?.length">
                      <thead><tr><th>Assertion</th><th>With Skill</th><th>Baseline</th></tr></thead>
                      <tbody>
                        <tr v-for="(a, ai) in run.with_assertions || run.baseline_assertions" :key="ai">
                          <td><span :title="a.description + (a.evidence ? '\n' + a.evidence : '')" class="bm-grade-text">{{ a.text }}</span></td>
                          <td><span :class="((run.with_assertions?.[ai] || a) as any)?.passed ? 'bm-pass' : 'bm-fail'">{{ ((run.with_assertions?.[ai] || a) as any)?.passed ? '✓' : '✕' }}</span></td>
                          <td><span :class="((run.baseline_assertions?.[ai] || a) as any)?.passed ? 'bm-pass' : 'bm-fail'">{{ ((run.baseline_assertions?.[ai] || a) as any)?.passed ? '✓' : '✕' }}</span></td>
                        </tr>
                        <tr class="bm-grade-total">
                          <td>{{ countPassed(run.with_assertions) }}/{{ (run.with_assertions||run.baseline_assertions)?.length||0 }} vs {{ countPassed(run.baseline_assertions) }}/{{ (run.baseline_assertions||run.with_assertions)?.length||0 }}</td>
                          <td><span class="bm-pass">{{ countPassed(run.with_assertions) }}/{{ (run.with_assertions||run.baseline_assertions)?.length||0 }}</span></td>
                          <td><span class="bm-fail">{{ countPassed(run.baseline_assertions) }}/{{ (run.baseline_assertions||run.with_assertions)?.length||0 }}</span></td>
                        </tr>
                      </tbody>
                    </table>
                    <div class="bm-result-meta" v-if="run.with_time">
                      <span title="执行时间">⏱ {{ run.with_time }}s / {{ run.baseline_time }}s</span>
                      <span title="Token 消耗">📊 {{ fmtNum(run.with_tokens) }} / {{ fmtNum(run.baseline_tokens) }}</span>
                    </div>
                  </div>
                </div>

                <!-- Stats table -->
                <div class="bm-stats-card" v-if="benchmarkResult.stats">
                  <div class="bm-stats-title">统计汇总</div>
                  <table class="bm-stats-table">
                    <thead><tr><th>Metric</th><th>With Skill</th><th>Baseline</th><th>Delta</th></tr></thead>
                    <tbody>
                      <tr>
                        <td>Assertion Pass</td>
                        <td class="bm-stats-val">{{ fmtStat(benchmarkResult.stats.with_skill.assertion_pass_rate) }}</td>
                        <td class="bm-stats-val">{{ fmtStat(benchmarkResult.stats.without_skill.assertion_pass_rate) }}</td>
                        <td :class="benchmarkResult?.stats?.delta?.assertion_pass_rate?.startsWith?.('-') ? 'bm-delta-down' : 'bm-delta-up'">{{ benchmarkResult.stats.delta.assertion_pass_rate }}</td>
                      </tr>
                      <tr>
                        <td>Time (s)</td>
                        <td class="bm-stats-val">{{ fmtStat(benchmarkResult.stats.with_skill.time_seconds) }}</td>
                        <td class="bm-stats-val">{{ fmtStat(benchmarkResult.stats.without_skill.time_seconds) }}</td>
                        <td :class="benchmarkResult?.stats?.delta?.time_seconds?.startsWith?.('-') ? 'bm-delta-down' : 'bm-delta-up'">{{ benchmarkResult.stats.delta.time_seconds }}</td>
                      </tr>
                      <tr>
                        <td>Tokens</td>
                        <td class="bm-stats-val">{{ fmtStat(benchmarkResult.stats.with_skill.tokens) }}</td>
                        <td class="bm-stats-val">{{ fmtStat(benchmarkResult.stats.without_skill.tokens) }}</td>
                        <td :class="benchmarkResult?.stats?.delta?.tokens?.startsWith?.('-') ? 'bm-delta-down' : 'bm-delta-up'">{{ benchmarkResult.stats.delta.tokens }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <!-- LLM summary bar -->
                <div class="bm-summary-bar" v-if="benchmarkResult.pass_rate !== undefined">
                  <span>LLM 盲比通过率 <b>{{ (benchmarkResult.pass_rate * 100).toFixed(0) }}%</b></span>
                  <span :class="benchmarkResult.delta?.startsWith?.('+') ? 'up' : 'down'">Δ {{ benchmarkResult.delta }}</span>
                  <span>评分 <b>{{ benchmarkResult.score }}/100</b></span>
                </div>
              </div>
            </div>
          </el-tab-pane>

          <!-- ===== TAB 3: 优化 ===== -->
          <el-tab-pane name="optimize">
            <template #label>
              优化
              <span v-if="optimizedContent" class="bm-tab-dot" title="优化方案已生成"></span>
            </template>
          <div class="bm-opt-page">
            <!-- Header -->
            <div class="bm-phase-header" v-if="optimizedContent">
              <el-button size="small" @click="showDiff = !showDiff" class="bm-opt-toggle">
                {{ showDiff ? '← 单栏编辑' : '对比查看 →' }}
              </el-button>
            </div>

            <!-- State: No evaluation yet, or LLM evaluation still running -->
            <div class="bm-opt-empty" v-if="!evaluation?.suggestions?.length">
              <el-icon v-if="llmEvaluating" class="is-loading" :size="20"><Loading /></el-icon>
              <el-icon v-else :size="20"><InfoFilled /></el-icon>
              <span>{{ llmEvaluating ? 'LLM 深度评估进行中，评估完成后自动生成优化方案...' : '请先在「评估」页签完成 LLM 深度评估' }}</span>
            </div>

            <!-- State: Optimizing -->
            <div class="bm-opt-empty" v-else-if="optimizing">
              <el-icon class="is-loading" :size="20"><Loading /></el-icon>
              <span>正在生成优化方案...</span>
            </div>

            <!-- State: Has optimized content -->
            <template v-else-if="optimizedContent">
              <div class="bm-opt-source" v-if="optimizeSourceHint">{{ optimizeSourceHint }}</div>

              <!-- Edit mode -->
              <div class="bm-opt-editor" v-if="!showDiff">
                <el-input v-model="optimizedContent" type="textarea" :rows="16" class="monospace-input" />
                <div class="bm-opt-actions">
                  <el-button size="small" @click="copyOptimized"><el-icon><CopyDocument /></el-icon> 复制</el-button>
                  <button class="pc-glow-btn primary" @click="applyOptimization" style="font-size:13px;padding:6px 18px">
                    <el-icon><Check /></el-icon> 应用到技能
                  </button>
                </div>
              </div>

              <!-- Diff mode -->
              <div class="bm-opt-diff" v-else>
                <div class="bm-opt-diff-panes">
                  <div class="bm-opt-diff-pane">
                    <div class="bm-opt-diff-title">原始版本</div>
                    <div class="bm-opt-diff-content"><code><div v-for="(line, li) in computeDiff(fileContent, optimizedContent)" :key="'o'+li" :class="line.type === 'remove' ? 'diff-remove' : 'diff-same'" v-show="line.type !== 'add'">{{ line.text || ' ' }}</div></code></div>
                  </div>
                  <div class="bm-opt-diff-pane">
                    <div class="bm-opt-diff-title">优化版本</div>
                    <div class="bm-opt-diff-content"><code><div v-for="(line, li) in computeDiff(fileContent, optimizedContent)" :key="'n'+li" :class="line.type === 'add' ? 'diff-add' : 'diff-same'" v-show="line.type !== 'remove'">{{ line.text || ' ' }}</div></code></div>
                  </div>
                </div>
              </div>
            </template>

            <!-- State: Has evaluation but no optimized content yet -->
            <div class="bm-opt-empty" v-else>
              <span>评估已完成，优化方案未生成</span>
              <button class="pc-glow-btn primary" @click="runOptimize" style="font-size:13px;padding:6px 18px">
                <el-icon><MagicStick /></el-icon> 生成优化方案
              </button>
            </div>
          </div>
          </el-tab-pane>
        </el-tabs>

        <!-- Placeholder when no evaluation -->
        <div v-else>
          <div class="eval-placeholder">
            <div class="placeholder-icon">
              <el-icon :size="48"><MagicStick /></el-icon>
            </div>
            <div class="placeholder-title">Skill 评估与优化</div>
            <div class="placeholder-desc">
              选择左侧 Skill，点击"评估"按钮，AI 将按 8 个维度对 Skill 进行打分并给出优化建议。
            </div>
            <div class="dimension-preview">
              <span class="dim-tag">清晰度</span>
              <span class="dim-tag">完整性</span>
              <span class="dim-tag">简洁度</span>
              <span class="dim-tag">结构规范</span>
              <span class="dim-tag">触发精准</span>
              <span class="dim-tag">依赖声明</span>
              <span class="dim-tag">配置合理性</span>
              <span class="dim-tag">安全性</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { api, longApi } from '@/api'
import { getAccessToken } from '@/stores/user'
import { marked } from 'marked'
import {
  InfoFilled, MagicStick, Loading, FolderOpened, Document, Folder,
  Memo, Warning, CopyDocument, Check, Download, Close, Plus
} from '@element-plus/icons-vue'

const { t: $t } = useI18n()

const dimLabelMap: Record<string, string> = {
  clarity: '清晰度',
  completeness: '完整性',
  conciseness: '简洁度',
  trigger: '触发精准',
  dependencies: '依赖声明',
}

// ── Skill list ──
interface SkillInfo {
  id?: number
  name: string
  display_name: string
  description: string
  source: string
  scope: string
  enabled: boolean
  skill_format: string
}

interface FileEntry {
  name: string
  path: string
  type: string
  size: number
  children?: FileEntry[]
}

interface RuleResult {
  rule_id: string
  description: string
  severity: string
  passed: boolean
  line: number
  snippet: string
}

interface StructureCheck {
  check: string
  passed: boolean
  score: number
  max_score: number
  detail: string
}

interface LlmDimension {
  key: string
  label: string
  score: number
  comment: string
}

interface AssertionResult {
  text: string
  description?: string
  passed: boolean
  evidence?: string
}

interface StatItem { mean: number; stddev: number; min: number; max: number }

interface BenchmarkRun {
  prompt: string
  with_skill_output: string
  baseline_output: string
  passed: boolean
  reasoning: string
  with_assertions?: AssertionResult[]
  baseline_assertions?: AssertionResult[]
  with_time?: number
  baseline_time?: number
  with_tokens?: number
  baseline_tokens?: number
}

interface BenchmarkResult {
  pass_rate: number
  delta: string
  score: number
  summary: string
  runs: BenchmarkRun[]
  assertion_summary?: { total: number; with_skill_passed: number; baseline_passed: number }
  stats?: {
    with_skill: { assertion_pass_rate: StatItem; time_seconds: StatItem; tokens: StatItem }
    without_skill: { assertion_pass_rate: StatItem; time_seconds: StatItem; tokens: StatItem }
    delta: { assertion_pass_rate: string; time_seconds: string; tokens: string }
  }
}

interface Suggestion {
  title: string
  detail: string
  severity: string
}

interface Evaluation {
  overall_score: number
  summary: string
  safety_score: number
  safety_hits: number
  safety_rules: RuleResult[]
  structure_score: number
  structure_checks: StructureCheck[]
  llm_dimensions: LlmDimension[]
  benchmark: BenchmarkResult | null
  suggestions: Suggestion[]
  optimized_content: string
  llm_pending?: boolean
}

const activeTab = ref('evaluate')
const loadingSkills = ref(false)
const skills = ref<SkillInfo[]>([])
const selectedSkillName = ref('')
const selectedSkill = ref<SkillInfo | null>(null)

// ── File tree ──
const fileTree = ref<FileEntry[]>([])
const treeProps = { children: 'children', label: 'name' }
const activeFile = ref('SKILL.md')
const fileContent = ref('')

// ── Frontmatter 解析 ──
function parseFrontmatter(content: string): { meta: Record<string, any>; body: string } {
  const match = content.match(/^---\n([\s\S]*?)\n---\n?/)
  if (!match) return { meta: {}, body: content }
  const yaml = match[1]
  const body = content.slice(match[0].length)
  const meta: Record<string, any> = {}
  const lines = yaml.split('\n')
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const colonIdx = line.indexOf(':')
    if (colonIdx === -1) { i++; continue }
    const key = line.slice(0, colonIdx).trim()
    let value = line.slice(colonIdx + 1).trim()
    // YAML 多行值: > (folded) 或 | (literal)
    if (value === '>' || value === '|' || value === '>-' || value === '|-') {
      const parts: string[] = []
      while (i + 1 < lines.length && (lines[i + 1].startsWith('  ') || lines[i + 1].startsWith('\t'))) {
        i++
        parts.push(lines[i].trim())
      }
      value = parts.join(' ')
      // 去引号
    } else if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1)
    }
    if (value.startsWith('[') && value.endsWith(']')) {
      meta[key] = value.slice(1, -1).split(',').map(s => s.trim())
    } else {
      meta[key] = value
    }
    i++
  }
  return { meta, body }
}

// ── File extension → render mode ──
const isMarkdownFile = computed(() => {
  const name = activeFile.value.toLowerCase()
  return name.endsWith('.md') || name.endsWith('.markdown')
})

const codeExtensions = ['.py', '.js', '.ts', '.json', '.yaml', '.yml', '.sh', '.bat', '.ps1',
  '.jsx', '.tsx', '.vue', '.css', '.scss', '.html', '.xml', '.toml', '.ini', '.cfg',
  '.sql', '.go', '.rs', '.java', '.c', '.cpp', '.h', '.rb', '.php', '.swift',
  '.txt', '.rst', '.csv', '.log']

const isCodeFile = computed(() => {
  const name = activeFile.value.toLowerCase()
  return codeExtensions.some(ext => name.endsWith(ext))
})

// ── Rendered content ──
const renderedContent = computed(() => {
  if (!fileContent.value) return ''
  if (isMarkdownFile.value) {
    const { body } = parseFrontmatter(fileContent.value)
    try {
      return marked.parse(body) as string
    } catch {
      return `<pre>${escapeHtml(body)}</pre>`
    }
  }
  if (isCodeFile.value) {
    const ext = activeFile.value.split('.').pop()?.toLowerCase() || ''
    return `<pre class="code-block"><code class="language-${ext}">${escapeHtml(fileContent.value)}</code></pre>`
  }
  return `<pre class="code-block"><code>${escapeHtml(fileContent.value)}</code></pre>`
})

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

// ── Evaluation ──
const evaluating = ref(false)
const evaluation = ref<Evaluation | null>(null)
const optimizedContent = ref('')
const safetyCollapse = ref<string[]>([])
const structureCollapse = ref<string[]>([])
const llmCollapse = ref<string[]>(['llm'])
const showDiff = ref(false)

// ── Optimize ──
const optimizing = ref(false)

// ── Benchmark ──
const benchmarking = ref(false)
const generatingPrompts = ref(false)
const generatedEvals = ref<{ prompt: string; expected: string; assertions: { text: string; description: string }[] }[]>([
  { prompt: '', expected: '', assertions: [] },
  { prompt: '', expected: '', assertions: [] },
])
const benchmarkResult = ref<any>(null)
const streamResults = ref<any[]>([])
const benchmarkPercent = ref(0)

// ── LLM Evaluation ──
const llmEvaluating = ref(false)


// ── Methods ──
function getScopeLabel(scope: string): string {
  const m: Record<string, string> = { user: '本地', org: '组织', system: '系统' }
  return m[scope] || scope
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1048576).toFixed(1)} MB`
}

function scoreColor(score: number, loading: boolean = false): string {
  if (loading) return '#9ca3af'
  if (score >= 80) return '#22c55e'
  if (score >= 60) return '#f59e0b'
  return '#ef4444'
}

function scoreGlowColor(score: number, loading: boolean = false): string {
  if (loading) return '#d1d5db'
  if (score >= 80) return '#4ade80'
  if (score >= 60) return '#fbbf24'
  return '#f87171'
}

const ringRadius = 50
const circumference = 2 * Math.PI * ringRadius
const dashOffset = computed(() =>
  circumference - (circumference * (evaluation.value?.overall_score ?? 0)) / 100
)

const llmAvgScore = computed(() => {
  const dims = evaluation.value?.llm_dimensions
  if (!dims || dims.length === 0) return 0
  return Math.round(dims.reduce((s, d) => s + d.score, 0) / dims.length)
})

async function fetchSkills() {
  loadingSkills.value = true
  try {
    const res = await api.get('/skill-eval/skills')
    skills.value = res.data || []
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载技能列表失败')
  } finally {
    loadingSkills.value = false
  }
}

async function onSkillChange(name: string) {
  const skill = skills.value.find(s => s.name === name)
  selectedSkill.value = skill || null
  evaluation.value = null
  optimizedContent.value = ''
  activeFile.value = 'SKILL.md'
  fileContent.value = ''
  // Reset benchmark state when switching skills
  generatedEvals.value = [
    { prompt: '', expected: '', assertions: [] },
    { prompt: '', expected: '', assertions: [] },
  ]
  benchmarkResult.value = null
  streamResults.value = []

  if (!skill) return

  // 加载文件树
  try {
    const res = await api.get(`/skill-eval/skills/${encodeURIComponent(name)}/tree`)
    fileTree.value = res.data.tree || []

    // 如果有直接返回的 content（DB 技能），直接显示
    if (res.data.content) {
      setFileContent(res.data.content)
    } else if (fileTree.value.length > 0) {
      // 加载第一个文件的内容
      const firstFile = fileTree.value.find((f: FileEntry) => f.type === 'file')
      if (firstFile) {
        activeFile.value = firstFile.name
        await loadFileContent(firstFile.path)
      }
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载文件树失败')
  }
}

async function onFileClick(data: FileEntry) {
  if (data.type !== 'file') return
  activeFile.value = data.name
  await loadFileContent(data.path)
}

function setFileContent(content: string) {
  fileContent.value = content
}

async function loadFileContent(path: string) {
  try {
    const res = await api.get(
      `/skill-eval/skills/${encodeURIComponent(selectedSkillName.value)}/file`,
      { params: { path } }
    )
    setFileContent(res.data.content || '')
  } catch (e: any) {
    ElMessage.error('加载文件内容失败')
    fileContent.value = ''
  }
}

async function runEvaluation() {
  if (!selectedSkillName.value) return
  evaluating.value = true
  evaluation.value = null
  llmEvaluating.value = false

  // 始终以 SKILL.md 内容为准
  let skillMdContent = fileContent.value
  if (activeFile.value !== 'SKILL.md') {
    try {
      const res = await api.get(
        `/skill-eval/skills/${encodeURIComponent(selectedSkillName.value)}/file`,
        { params: { path: 'SKILL.md' } }
      )
      skillMdContent = res.data.content || ''
    } catch { /* 保持当前内容 */ }
  }

  // ── Step 1: 快速评估（safety + structure，秒出）──
  try {
    const res = await api.post(
      `/skill-eval/skills/${encodeURIComponent(selectedSkillName.value)}/evaluate`,
      { content: skillMdContent }
    )
    evaluation.value = res.data
    safetyCollapse.value = []
    structureCollapse.value = []
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '评估请求失败，请检查后端服务')
    evaluating.value = false
    return
  } finally {
    evaluating.value = false
  }

  // ── Step 2: LLM 深度评估（异步，耗时较长）──
  llmEvaluating.value = true
  try {
    const reqSafety = evaluation.value?.safety_score ?? 0
    const reqStructure = evaluation.value?.structure_score ?? 0
    const llmRes = await longApi.post(
      `/skill-eval/skills/${encodeURIComponent(selectedSkillName.value)}/evaluate-llm`,
      {
        content: skillMdContent,
        safety_score: reqSafety,
        structure_score: reqStructure,
      }
    )
    const llmData = llmRes.data || {}
    console.log('[SkillEval] LLM response:', JSON.stringify(llmData).slice(0, 300))
    if (llmData.dimensions && Array.isArray(llmData.dimensions)) {
      llmData.dimensions.forEach((d: any) => console.log('  dim:', d.key, 'score=', d.score, 'comment=', d.comment))
    } else {
      console.log('[SkillEval] No dimensions in response, llmData keys:', Object.keys(llmData))
    }
    if (evaluation.value) {
      evaluation.value.llm_dimensions = llmData.dimensions
      evaluation.value.suggestions = llmData.suggestions
      evaluation.value.optimized_content = ''
      evaluation.value.llm_pending = false
      // 防御性修复：如果后端没返回 overall_score，保留之前 safety+structure 的分数
      const prevScore = evaluation.value.overall_score
      evaluation.value.overall_score = (typeof llmData.overall_score === 'number') ? llmData.overall_score : prevScore
      console.log('[SkillEval] overall_score set to:', evaluation.value.overall_score, '(was:', prevScore, ')')
      if (llmData.summary) {
        evaluation.value.summary = evaluation.value.summary.replace('。其余维度待深度评测。', '')
        evaluation.value.summary += '；' + llmData.summary
      }

      // Auto-generate optimization after LLM evaluation
      if (llmData.suggestions?.length) {
        runOptimize().catch(() => {}) // fire-and-forget
      }
    }
  } catch (e: any) {
    console.error('[SkillEval] LLM 评估失败:', e)
    // Try to extract error from response
    const errMsg = e?.response?.data?.detail || e?.message || String(e)
    console.log('[SkillEval] Error detail:', errMsg)
    if (evaluation.value) {
      evaluation.value.llm_dimensions = [
        { key: 'clarity', label: '清晰度', score: 0, comment: errMsg.slice(0, 40) },
        { key: 'completeness', label: '完整性', score: 0, comment: errMsg.slice(0, 40) },
        { key: 'conciseness', label: '简洁度', score: 0, comment: errMsg.slice(0, 40) },
        { key: 'trigger', label: '触发精准', score: 0, comment: errMsg.slice(0, 40) },
        { key: 'dependencies', label: '依赖声明', score: 0, comment: errMsg.slice(0, 40) },
      ]
      evaluation.value.llm_pending = false
    }
  } finally {
    llmEvaluating.value = false
    // Ensure dimensions are always set
    if (evaluation.value && !evaluation.value.llm_dimensions?.length) {
      evaluation.value.llm_dimensions = [
        { key: 'clarity', label: '清晰度', score: 0, comment: '评估未完成' },
        { key: 'completeness', label: '完整性', score: 0, comment: '评估未完成' },
        { key: 'conciseness', label: '简洁度', score: 0, comment: '评估未完成' },
        { key: 'trigger', label: '触发精准', score: 0, comment: '评估未完成' },
        { key: 'dependencies', label: '依赖声明', score: 0, comment: '评估未完成' },
      ]
    }
  }
}

async function applyOptimization() {
  if (!optimizedContent.value || !selectedSkill.value) return
  if (selectedSkill.value.source === 'db' && selectedSkill.value.id) {
    try {
      await api.put(`/skills/${selectedSkill.value.id}`, { content: optimizedContent.value })
      ElMessage.success('优化版本已应用')
      fileContent.value = optimizedContent.value
    } catch (e: any) {
      ElMessage.error(e.response?.data?.detail || '应用失败')
    }
  } else {
    // 文件系统技能 — 提示用户手动更新
    ElMessage.info('文件系统技能暂不支持自动保存，请手动复制优化内容')
  }
}

const optimizeSourceHint = ref('')

async function runOptimize() {
  if (!selectedSkillName.value || !evaluation.value) return
  optimizing.value = true
  optimizeSourceHint.value = ''
  try {
    const body: any = {
      content: fileContent.value,
      suggestions: evaluation.value.suggestions,
    }
    // Attach benchmark context if available
    if (benchmarkResult.value) {
      body.benchmark = {
        assertion_summary: benchmarkResult.value.assertion_summary,
        stats: benchmarkResult.value.stats,
        pass_rate: benchmarkResult.value.pass_rate,
        runs: benchmarkResult.value.runs?.map((r: any) => ({
          prompt: r.prompt,
          with_pass: r.with_assertions?.filter((a: any) => a.passed).length || 0,
          with_total: r.with_assertions?.length || 0,
          baseline_pass: r.baseline_assertions?.filter((a: any) => a.passed).length || 0,
          baseline_total: r.baseline_assertions?.length || 0,
        })),
      }
    }
    const res = await longApi.post(
      `/skill-eval/skills/${encodeURIComponent(selectedSkillName.value)}/optimize`,
      body
    )
    optimizedContent.value = res.data.optimized_content || ''
    const parts = ['基于评估建议']
    if (evaluation.value?.suggestions?.length) parts.push(`（${evaluation.value.suggestions.length} 条）`)
    if (body.benchmark) parts.push(' + Benchmark 实测结果')
    optimizeSourceHint.value = parts.join('')
    ElMessage.success('优化完成')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '优化请求失败')
  } finally {
    optimizing.value = false
  }
}

// ── Computed ──
const hasPrompts = computed(() => generatedEvals.value.some(e => e.prompt.trim()))
const activePromptCount = computed(() => generatedEvals.value.filter(e => e.prompt.trim()).length)

// ── Benchmark helpers ──
function countPassed(assertions?: { passed: boolean }[]) {
  if (!assertions?.length) return 0
  return assertions.filter(a => a.passed).length
}
function fmtStat(s?: { mean: number; stddev: number }) {
  if (!s) return '-'
  return `${s.mean.toFixed(1)} ± ${s.stddev.toFixed(1)}`
}
function fmtNum(n?: number) {
  if (!n) return '0'
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)
}

function addPrompt() {
  generatedEvals.value.push({ prompt: '', expected: '', assertions: [] })
}
function removePrompt(idx: number) {
  generatedEvals.value.splice(idx, 1)
}
function addAssertion(promptIdx: number) {
  generatedEvals.value[promptIdx].assertions.push({ text: '', description: '' })
}
function removeAssertion(promptIdx: number, assertionIdx: number) {
  generatedEvals.value[promptIdx].assertions.splice(assertionIdx, 1)
}

async function generateTestPrompts() {
  if (!selectedSkillName.value) return
  generatingPrompts.value = true
  try {
    const res = await api.post(
      `/skill-eval/skills/${encodeURIComponent(selectedSkillName.value)}/generate-prompts`,
      { content: fileContent.value }
    )
    const evals = res.data.evals || res.data.prompts || []
    generatedEvals.value = evals.map((e: any) => ({
      prompt: typeof e === 'string' ? e : (e.prompt || ''),
      expected: e.expected || '',
      assertions: (e.assertions || []).map((a: any) => ({
        text: a.text || '',
        description: a.description || '',
      })),
    }))
    ElMessage.success(`已生成 ${generatedEvals.value.length} 个测试用例`)
  } catch (e: any) {
    const skillName = selectedSkillName.value
    generatedEvals.value = [
      { prompt: `请使用 ${skillName} 技能完成一个典型任务`, expected: '', assertions: [] },
      { prompt: `帮我用 ${skillName} 处理一个常见场景`, expected: '', assertions: [] },
    ]
    ElMessage.info('已生成默认测试 Prompt')
  } finally {
    generatingPrompts.value = false
  }
}

function handleStreamEvent(event: any) {
  if (event.type === 'result') {
    streamResults.value.push({
      ...event.run,
      with_assertions: event.run.with_assertions || [],
      baseline_assertions: event.run.baseline_assertions || [],
    })
    benchmarkPercent.value = Math.round(streamResults.value.length / activePromptCount.value * 100)
  } else if (event.type === 'summary') {
    benchmarkResult.value = event
    benchmarkPercent.value = 100
  }
}

async function runBenchmark() {
  if (!selectedSkillName.value) return
  const filtered = generatedEvals.value.filter(e => e.prompt.trim())
  if (!filtered.length) { ElMessage.warning('请至少输入一个测试提示词'); return }
  benchmarking.value = true
  benchmarkResult.value = null
  streamResults.value = []
  benchmarkPercent.value = 0

  try {
    const token = getAccessToken()
    const url = `/api/skill-eval/skills/${encodeURIComponent(selectedSkillName.value)}/benchmark-stream`

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({
        test_prompts: filtered.map(e => ({
          prompt: e.prompt.trim(),
          expected: e.expected || '',
          assertions: e.assertions || [],
        }))
      })
    })

    if (!response.ok) {
      const errText = await response.text()
      let errDetail = response.statusText
      try {
        const errJson = JSON.parse(errText)
        errDetail = errJson.detail || errDetail
      } catch {}
      throw new Error(errDetail)
    }

    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const event = JSON.parse(line.slice(6))
            handleStreamEvent(event)
          } catch {
            // skip malformed JSON lines
          }
        }
      }
    }
  } catch (e: any) {
    const errMsg = e.message || '实测请求失败'
    ElMessage.error(errMsg)
  } finally {
    benchmarking.value = false
  }
}

function copyContent() {
  navigator.clipboard.writeText(fileContent.value)
  ElMessage.success($t('common.copied'))
}

function copyOptimized() {
  navigator.clipboard.writeText(optimizedContent.value)
  ElMessage.success($t('common.copied'))
}

function computeDiff(original: string, optimized: string) {
  const oLines = original.split('\n')
  const nLines = optimized.split('\n')
  const result: { type: 'same' | 'add' | 'remove'; text: string }[] = []
  // Simple line-by-line diff using LCS-like approach
  let oi = 0, ni = 0
  while (oi < oLines.length || ni < nLines.length) {
    if (oi >= oLines.length) {
      result.push({ type: 'add', text: nLines[ni++] }); continue
    }
    if (ni >= nLines.length) {
      result.push({ type: 'remove', text: oLines[oi++] }); continue
    }
    if (oLines[oi] === nLines[ni]) {
      result.push({ type: 'same', text: oLines[oi] }); oi++; ni++
    } else {
      // Look ahead for match
      const aheadO = oLines.indexOf(nLines[ni], oi + 1)
      const aheadN = nLines.indexOf(oLines[oi], ni + 1)
      if ((aheadO === -1 && aheadN === -1) || (aheadN !== -1 && aheadO !== -1 && aheadN - ni <= aheadO - oi) || (aheadN !== -1 && aheadO === -1)) {
        result.push({ type: 'remove', text: oLines[oi++] })
      } else if (aheadO !== -1 && (aheadN === -1 || aheadO - oi < aheadN - ni)) {
        result.push({ type: 'add', text: nLines[ni++] })
      } else {
        result.push({ type: 'add', text: nLines[ni++] })
        result.push({ type: 'remove', text: oLines[oi++] })
      }
    }
  }
  return result
}

function downloadReport() {
  if (!evaluation.value) return
  const e = evaluation.value as any
  const name = selectedSkillName.value || 'skill'

  const dimRows = (e.llm_dimensions || e.dimensions || []).map((d: any) =>
    `<tr><td>${d.label || d.key}</td><td style="font-weight:700;color:var(--score)">${d.score}</td><td style="font-size:.82em;color:var(--muted)">${d.comment || ''}</td></tr>`
  ).join('')

  const checkRows = (e.structure_checks || []).map((c: any) =>
    `<tr><td>${c.check}</td><td><span class="badge ${c.passed ? 'badge-pass' : 'badge-fail'}">${c.passed ? '✓ 通过' : '✗ 失败'}</span></td><td>${c.score}/${c.max_score}</td><td style="font-size:.8em;color:var(--muted)">${c.detail || ''}</td></tr>`
  ).join('')

  const ruleRows = (e.safety_rules || e.redflag_hits || []).map((r: any) => {
    const sev = r.severity || 'HIGH'
    const sevColor = sev === 'CRITICAL' ? 'var(--red)' : 'var(--amber)'
    const passed = r.passed !== undefined ? r.passed : false
    return `<tr><td style="font-family:monospace;font-size:.8em">${r.rule_id}</td><td style="color:${sevColor};font-weight:600;font-size:.75em">${sev}</td><td style="font-size:.85em">${r.description}</td><td><span class="badge ${passed ? 'badge-pass' : 'badge-fail'}">${passed ? '✓' : '✕'}</span></td></tr>`
  }).join('')

  const sugItems = (e.suggestions || []).map((s: any) =>
    `<div class="card"><div style="font-weight:600;margin-bottom:4px">${s.title}</div><div style="font-size:.82em;color:var(--muted)">${s.detail || ''}</div><span class="badge" style="background:rgba(255,77,106,.1);color:var(--red)">${s.severity || 'medium'}</span></div>`
  ).join('')

  const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>Skill 评估报告 - ${name}</title>
<style>
:root{--bg:#0a0e1a;--surface:#161b2e;--border:#2a2a4a;--primary:#00d4ff;--text:#e8eaf0;--muted:#7a7e92;--green:#00e5a0;--red:#ff4d6a;--amber:#ff8c42;--radius:10px}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text);max-width:800px;margin:0 auto;padding:24px 20px;line-height:1.6}
h1{font-size:1.4em;margin-bottom:4px}h2{font-size:1em;margin:24px 0 12px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px 20px;margin-bottom:12px}
.badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:.75em;font-weight:600}
.badge-pass{background:rgba(0,229,160,.1);color:var(--green)}.badge-fail{background:rgba(255,77,106,.1);color:var(--red)}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--border);font-size:.9em}
th{color:var(--muted);font-size:.75em;text-transform:uppercase}
.score{font-size:2.5em;font-weight:800;color:var(--primary)}
</style></head><body>
<h1>Skill 评估报告 — ${name}</h1>
<div class="card" style="text-align:center"><div style="font-size:3em;font-weight:800;color:var(--primary)">${e.overall_score || 0}</div><div style="color:var(--muted)">综合评分 /100</div></div>
<div class="card"><div class="score">${e.structure_score || e.structureScore || 0}</div><div style="color:var(--muted)">结构评分 /100</div></div>
<div class="card"><div class="score">${e.safety_score || e.safetyScore || 0}</div><div style="color:var(--muted)">安全评分 /100</div></div>
${e.summary ? `<div class="card"><p style="font-size:.9em">${e.summary}</p></div>` : ''}
${dimRows ? `<h2>LLM 深度评估</h2><table><tr><th>维度</th><th>评分</th><th>评语</th></tr>${dimRows}</table>` : ''}
${checkRows ? `<h2>结构检查</h2><table><tr><th>检查项</th><th>状态</th><th>得分</th><th>详情</th></tr>${checkRows}</table>` : ''}
${ruleRows ? `<h2>安全红线扫描</h2><table><tr><th>规则</th><th>严重度</th><th>描述</th><th>状态</th></tr>${ruleRows}</table>` : ''}
${sugItems ? `<h2>修改建议</h2>${sugItems}` : ''}
<div style="margin-top:24px;padding-top:16px;border-top:1px solid var(--border);font-size:.75em;color:var(--muted);text-align:center">Generated by PioneClaw Skill Evaluator</div>
</body></html>`

  const blob = new Blob([html], { type: 'text/html' })
  const url = URL.createObjectURL(blob)
  window.open(url, '_blank')
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

onMounted(fetchSkills)
</script>

<style scoped lang="scss">
.skill-eval-page {
  padding: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
}

// ── Eval Container ──
.eval-container {
  display: flex;
  gap: 16px;
  flex: 1;
  min-height: 0;
}

// ── Left Panel ──
.left-panel {
  width: 42%;
  min-width: 380px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: hidden;
}

.skill-selector {
  flex-shrink: 0;

  .skill-option {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;

    .skill-option-name {
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .scope-tag {
      margin-left: auto;
    }
  }

  :deep(.el-select) {
    .el-input__wrapper {
      background: var(--pc-glass-bg) !important;
      border: 1px solid var(--pc-glass-border) !important;
      box-shadow: none !important;
    }
    .el-input__inner {
      color: var(--pc-text-primary);
    }
  }
}

.file-tree-panel {
  background: var(--pc-glass-bg);
  border: 1px solid var(--pc-glass-border);
  border-radius: var(--pc-radius-md);
  backdrop-filter: var(--pc-glass-blur);
  flex-shrink: 0;
  max-height: 200px;
  overflow: hidden;
  display: flex;
  flex-direction: column;

  .panel-label {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 10px 14px;
    font-size: 12px;
    font-weight: 600;
    color: var(--pc-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 1px solid var(--pc-border);
  }

  :deep(.el-tree) {
    background: transparent;
    padding: 6px 8px;
    overflow-y: auto;
    flex: 1;

    .el-tree-node__content {
      padding: 3px 6px;
      border-radius: 4px;
      color: var(--pc-text-secondary);
      transition: all 0.15s;

      &:hover {
        background: rgba(var(--pc-primary-rgb), 0.06);
        color: var(--pc-text-primary);
      }
    }

    .el-tree-node.is-current > .el-tree-node__content {
      background: rgba(var(--pc-primary-rgb), 0.1);
      color: var(--pc-primary);
    }
  }

  .tree-node {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;

    .tree-node-name {
      flex: 1;
    }

    .tree-node-size {
      font-size: 11px;
      color: var(--pc-text-muted);
    }
  }
}

.file-content-panel {
  flex: 1;
  min-height: 0;
  background: var(--pc-glass-bg);
  border: 1px solid var(--pc-glass-border);
  border-radius: var(--pc-radius-md);
  backdrop-filter: var(--pc-glass-blur);
  display: flex;
  flex-direction: column;
  overflow: hidden;

  .panel-label {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 10px 14px;
    font-size: 12px;
    font-weight: 600;
    color: var(--pc-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 1px solid var(--pc-border);
    flex-shrink: 0;

    span {
      flex: 1;
    }

    .copy-btn {
      background: none;
      border: none;
      color: var(--pc-text-muted);
      cursor: pointer;
      padding: 2px 4px;
      border-radius: 4px;
      transition: all 0.15s;

      &:hover {
        color: var(--pc-primary);
        background: rgba(var(--pc-primary-rgb), 0.08);
      }
    }
  }

  .content-viewer {
    flex: 1;
    overflow-y: auto;
    padding: 14px 16px;
  }


  .content-empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    color: var(--pc-text-muted);
    font-size: 13px;
  }
}

// ── Markdown ──
.markdown-body {
  color: var(--pc-text-primary);
  font-size: 13.5px;
  line-height: 1.7;

  :deep(h1) { font-size: 1.5em; margin: 0 0 12px; padding-bottom: 6px; border-bottom: 1px solid var(--pc-border); }
  :deep(h2) { font-size: 1.25em; margin: 16px 0 8px; }
  :deep(h3) { font-size: 1.1em; margin: 12px 0 6px; }
  :deep(p) { margin: 0 0 10px; }
  :deep(code) {
    background: var(--pc-bg-deep);
    padding: 2px 6px;
    border-radius: 4px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.9em;
  }
  :deep(pre) {
    background: var(--pc-bg-deep);
    border: 1px solid var(--pc-border);
    border-radius: 6px;
    padding: 12px;
    overflow-x: auto;
    code { background: none; padding: 0; }
  }
  :deep(ul), :deep(ol) { padding-left: 20px; margin: 0 0 10px; }
  :deep(li) { margin: 2px 0; }
  :deep(blockquote) {
    border-left: 3px solid var(--pc-primary);
    padding-left: 12px;
    margin: 0 0 10px;
    color: var(--pc-text-muted);
  }
  :deep(table) {
    border-collapse: collapse;
    width: 100%;
    margin: 10px 0;
    th, td {
      border: 1px solid var(--pc-border);
      padding: 6px 10px;
      text-align: left;
    }
    th { background: var(--pc-bg-surface); font-weight: 600; }
  }
}

// ── Code blocks (non-Markdown files) ──
.code-block {
  background: var(--pc-bg-deep);
  border: 1px solid var(--pc-border);
  border-radius: 8px;
  padding: 14px 16px;
  overflow-x: auto;
  margin: 0;

  code {
    font-family: 'JetBrains Mono', 'Fira Code', 'Monaco', monospace;
    font-size: 12.5px;
    color: var(--pc-text-primary);
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-word;
    background: none;
    padding: 0;
  }
}

// ── Right Panel ──
.right-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
}

// ── Tabs ──
.eval-tabs {
  :deep(.el-tabs__header) { margin: 0 0 4px; }
  :deep(.el-tabs__nav-wrap::after) { display: none; }
  :deep(.el-tabs__item) {
    font-size: 13px; font-weight: 500; color: var(--pc-text-muted);
    padding: 0 20px; height: 40px; line-height: 40px;
    transition: color 0.2s;
    &:hover { color: var(--pc-text-primary); }
    &.is-active { color: var(--pc-primary); font-weight: 600; }
  }
  :deep(.el-tabs__active-bar) {
    background: var(--pc-primary); height: 2px; border-radius: 1px;
  }
}

.score-overview {
  background: var(--pc-glass-bg);
  border: 1px solid var(--pc-glass-border);
  border-radius: var(--pc-radius-lg);
  backdrop-filter: var(--pc-glass-blur);
  padding: 24px;
  display: flex;
  justify-content: center;

  .overall-circle {
    text-align: center;

    .overall-label {
      margin-top: 8px;
      font-size: 13px;
      color: var(--pc-text-muted);
      font-weight: 500;
    }
  }

  &.placeholder {
    justify-content: center;
    align-items: center;
    padding: 48px 24px;
    flex-direction: column;
    gap: 10px;
    color: var(--pc-text-muted);
    font-size: 13px;
  }
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--pc-text-primary);
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}

// ── Overall Score Card ──
.overall-card {
  background: var(--pc-glass-bg);
  border: 1px solid var(--pc-glass-border);
  margin-bottom: 14px;
  border-radius: 20px;
  backdrop-filter: var(--pc-glass-blur);
  padding: 28px 32px;
  display: flex;
  align-items: center;
  gap: 36px;
  flex-shrink: 0;

  .overall-info {
    .overall-title {
      font-size: 20px;
      font-weight: 700;
      color: var(--pc-text-primary);
      margin-bottom: 8px;
      letter-spacing: -0.01em;
    }
    .overall-summary {
      font-size: 13.5px;
      color: var(--pc-text-muted);
      line-height: 1.6;
    }
  }
}

.score-ring {
  position: relative;
  width: 140px;
  height: 140px;
  flex-shrink: 0;
  filter: drop-shadow(0 4px 20px rgba(var(--pc-primary-rgb), 0.12));

  svg {
    width: 100%;
    height: 100%;
    circle {
      transition: stroke-dashoffset 1s cubic-bezier(0.25, 0.46, 0.45, 0.94);
    }
  }

  .ring-center {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }

  .ring-value {
    font-size: 40px;
    font-weight: 800;
    line-height: 1;
    letter-spacing: -0.02em;
  }

  .ring-unit {
    font-size: 13px;
    color: var(--pc-text-muted);
    margin-top: 3px;
    font-weight: 500;
  }
}

// ── Dashboard Cards ──
.dashboard-card {
  background: var(--pc-glass-bg);
  border: 1px solid var(--pc-glass-border);
  border-radius: 14px;
  backdrop-filter: var(--pc-glass-blur);
  overflow: hidden;
  flex-shrink: 0;
  margin-bottom: 14px;
  transition: border-color 0.2s;

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    font-size: 13px;
    font-weight: 600;
    color: var(--pc-text-primary);
    border-bottom: 1px solid var(--pc-border);
    background: var(--pc-glass-bg);
  }

  &.muted { opacity: 0.6; }

  :deep(.el-collapse) {
    border: none;
    --el-collapse-header-bg-color: transparent;
    --el-collapse-content-bg-color: transparent;
  }

  :deep(.el-collapse-item__header) {
    background: var(--pc-bg-surface);
    border: none;
    border-bottom: 1px solid var(--pc-border);
    padding: 12px 16px;
    height: auto;
    line-height: 1.4;
    font-size: 14px;
    font-weight: 600;
    color: var(--pc-text-primary);
    border-radius: 20px 20px 0 0;
    transition: background 0.2s;
    &:hover { background: rgba(var(--pc-primary-rgb), 0.03); }
  }

  :deep(.el-collapse-item__wrap) {
    border: none;
    background: transparent;
  }

  :deep(.el-collapse-item__content) {
    padding: 0;
  }
}

.collapse-title {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  font-size: 14px;

  .collapse-sub {
    font-size: 12px;
    color: var(--pc-text-muted);
    font-weight: 400;
  }

  .collapse-score {
    margin-left: auto;
    font-size: 16px;
    font-weight: 700;
    padding: 2px 14px;
    border-radius: 14px;
    &.good { background: rgba(34, 197, 94, 0.1); color: #22c55e; }
    &.bad { background: rgba(239, 68, 68, 0.1); color: #ef4444; }
  }
}

// ── Rules Grid (Safety) ──
.rules-table {
  max-height: 400px;
  overflow-y: auto;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 12px;
}

.rule-row {
  background: var(--pc-bg-surface);
  border: 1px solid var(--pc-border);
  border-radius: 12px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: all 0.2s;

  &:hover {
    border-color: rgba(var(--pc-primary-rgb), 0.2);
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
  }

  &.row-fail {
    border-color: rgba(239, 68, 68, 0.3);
    background: rgba(239, 68, 68, 0.03);
    &:hover { box-shadow: 0 2px 12px rgba(239, 68, 68, 0.06); }
  }

  .rule-top {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .rule-status {
    font-size: 14px;
    flex-shrink: 0;
    &.pass { color: #22c55e; }
    &.fail { color: #ef4444; }
  }

  .rule-id {
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    color: var(--pc-text-muted);
    background: var(--pc-bg-deep);
    padding: 1px 5px;
    border-radius: 3px;
  }

  .rule-desc {
    flex: 1;
    color: var(--pc-text-primary);
    font-size: 12.5px;
    font-weight: 500;
  }

  .rule-severity {
    font-size: 9px;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 8px;
    text-transform: uppercase;
    flex-shrink: 0;
    &.critical { background: rgba(239, 68, 68, 0.12); color: #ef4444; }
    &.high { background: rgba(245, 158, 11, 0.12); color: #f59e0b; }
  }

  .rule-detail {
    margin-top: 2px;
    padding: 5px 8px;
    background: rgba(239, 68, 68, 0.06);
    border-radius: 4px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: #ef4444;
    word-break: break-all;
    code {
      background: var(--pc-bg-deep);
      padding: 1px 4px;
      border-radius: 2px;
      color: var(--pc-text-primary);
    }
  }
}

// ── Structure Checks Grid ──
.checks-list {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 12px;

  .check-row {
    background: var(--pc-bg-surface);
    border: 1px solid var(--pc-border);
    border-radius: 12px;
    padding: 12px 14px;
    display: flex;
    align-items: center;
    gap: 10px;
    transition: all 0.2s;

    &:hover {
      border-color: rgba(var(--pc-primary-rgb), 0.2);
      box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
    }

    .check-status {
      font-size: 16px;
      flex-shrink: 0;
      &.pass { color: #22c55e; }
      &.fail { color: #ef4444; }
    }
    .check-name {
      color: var(--pc-text-primary);
      font-weight: 600;
      font-size: 13px;
    }
    .check-detail {
      color: var(--pc-text-muted);
      margin-left: auto;
      font-family: 'JetBrains Mono', monospace;
      font-size: 12px;
    }
    .check-points {
      font-weight: 700;
      font-size: 12px;
      padding: 2px 8px;
      border-radius: 8px;
      flex-shrink: 0;
      &.got { background: rgba(34, 197, 94, 0.1); color: #22c55e; }
      &.miss { background: rgba(239, 68, 68, 0.1); color: #ef4444; }
    }
  }
}

// ── Placeholder Row ──
.placeholder-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 14px 16px;

  .dim-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 6px 16px;
    border-radius: 12px;
    background: var(--pc-bg-surface);
    border: 1px solid var(--pc-border);
    color: var(--pc-text-muted);
    font-size: 13px;
    font-weight: 500;
    transition: all 0.2s;
    &:hover {
      border-color: rgba(var(--pc-primary-rgb), 0.15);
      color: var(--pc-text-primary);
    }
  }
}

.suggestions-section {
  background: var(--pc-glass-bg);
  border: 1px solid var(--pc-glass-border);
  border-radius: var(--pc-radius-lg);
  backdrop-filter: var(--pc-glass-blur);
  padding: 16px;
}

.suggestion-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.suggestion-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  background: var(--pc-bg-surface);
  border: 1px solid var(--pc-border);
  border-radius: var(--pc-radius-md);

  .sg-index {
    flex-shrink: 0;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: rgba(var(--pc-primary-rgb), 0.1);
    color: var(--pc-primary);
    font-size: 11px;
    font-weight: 600;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .sg-body {
    flex: 1;
    .sg-title { font-size: 13px; font-weight: 600; color: var(--pc-text-primary); }
    .sg-detail { font-size: 12px; color: var(--pc-text-muted); margin-top: 2px; line-height: 1.4; }
  }
}

.optimized-section {
  background: var(--pc-glass-bg);
  border: 1px solid var(--pc-glass-border);
  border-radius: var(--pc-radius-lg);
  backdrop-filter: var(--pc-glass-blur);
  padding: 16px;
}

.optimized-editor {
  .monospace-input :deep(textarea) {
    font-family: 'JetBrains Mono', 'Fira Code', monospace !important;
    font-size: 12.5px;
    background: var(--pc-bg-deep);
    color: var(--pc-text-primary);
    border: 1px solid var(--pc-border);
    border-radius: 6px;
  }

  .editor-actions {
    display: flex;
    gap: 8px;
    margin-top: 10px;
    justify-content: flex-end;
  }
}

.diff-view {
  .diff-panes {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }

  .diff-pane {
    .diff-pane-title {
      font-size: 11px;
      font-weight: 600;
      color: var(--pc-text-muted);
      text-transform: uppercase;
      margin-bottom: 6px;
      padding: 4px 8px;
      background: var(--pc-bg-surface);
      border-radius: 4px;
    }

    .diff-content {
      background: var(--pc-bg-deep);
      border: 1px solid var(--pc-border);
      border-radius: 6px;
      padding: 10px;
      font-family: 'JetBrains Mono', 'Fira Code', monospace;
      font-size: 11.5px;
      color: var(--pc-text-primary);
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 420px;
      overflow-y: auto;
      line-height: 1.5;
    }
  }
}

// ── Placeholder ──
.eval-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 32px;
  text-align: center;

  .placeholder-icon {
    width: 80px;
    height: 80px;
    border-radius: 20px;
    background: rgba(var(--pc-primary-rgb), 0.08);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--pc-primary);
    margin-bottom: 16px;
  }

  .placeholder-title {
    font-size: 16px;
    font-weight: 600;
    color: var(--pc-text-primary);
    margin-bottom: 8px;
  }

  .placeholder-desc {
    font-size: 13px;
    color: var(--pc-text-muted);
    max-width: 360px;
    line-height: 1.6;
    margin-bottom: 16px;
  }

  .dimension-preview {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    justify-content: center;

    .dim-tag {
      padding: 4px 12px;
      border-radius: 20px;
      background: rgba(var(--pc-primary-rgb), 0.06);
      border: 1px solid rgba(var(--pc-primary-rgb), 0.15);
      color: var(--pc-primary);
      font-size: 12px;
      font-weight: 500;
    }
  }
}


// ── Cyberpunk buttons ──
.cyber-btn.primary-glow {
  box-shadow: 0 0 14px rgba(var(--pc-primary-rgb), 0.3);
  transition: box-shadow 0.25s;
  &:hover { box-shadow: 0 0 22px rgba(var(--pc-primary-rgb), 0.5); }
}

// ── LLM Dimension Cards ──
.dim-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.dim-card {
  background: var(--pc-glass-bg);
  border: 1px solid var(--pc-glass-border);
  border-radius: 12px;
  padding: 14px 16px;
  transition: transform 0.2s, box-shadow 0.2s;

  &:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
  }

  .dim-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;

    .dim-label {
      font-size: 13px;
      font-weight: 600;
      color: var(--pc-text-primary);
    }

    .dim-score {
      font-size: 18px;
      font-weight: 700;
    }
  }

  .dim-bar-bg {
    height: 5px;
    border-radius: 3px;
    background: var(--pc-border);
    overflow: hidden;
    margin-bottom: 8px;

    .dim-bar-fill {
      height: 100%;
      border-radius: 3px;
      transition: width 0.8s ease;
    }
  }

  .dim-comment {
    font-size: 12px;
    color: var(--pc-text-muted);
    line-height: 1.4;
  }
}

// ── Benchmark ──
/* ═══ Benchmark Page ═══ */
.bm-page { display: flex; flex-direction: column; gap: 16px; }

/* ── Phase container ── */
.bm-phase { display: flex; flex-direction: column; gap: 14px; }
.bm-phase-header { display: flex; align-items: center; justify-content: space-between; }
.bm-phase-title { font-size: 15px; font-weight: 700; color: var(--pc-text-primary); }

.bm-hint { font-size: 12px; color: var(--pc-text-muted); padding-bottom: 4px; }

/* ── Setup: Case Cards ── */
.bm-cases { display: flex; flex-direction: column; gap: 12px; }
.bm-case-card { background: var(--pc-bg-surface); border: 1px solid var(--pc-glass-border); border-radius: 10px; overflow: hidden; }
.bm-case-head { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: rgba(var(--pc-primary-rgb),0.04); border-bottom: 1px solid var(--pc-glass-border); }
.bm-case-num { width: 20px; height: 20px; border-radius: 50%; background: rgba(var(--pc-primary-rgb),0.15); color: var(--pc-primary); font-size: 10px; font-weight: 800; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.bm-case-label { font-size: 11px; font-weight: 600; color: var(--pc-text-muted); text-transform: uppercase; letter-spacing: 0.5px; }
.bm-case-body { display: flex; flex-direction: column; gap: 8px; padding: 10px 12px 12px; }
.bm-case-expected { margin-top: -2px; }

/* ── Setup: Assertions ── */
.bm-case-assertions { display: flex; flex-direction: column; gap: 4px; padding: 8px; background: rgba(var(--pc-primary-rgb),0.02); border-radius: 6px; border: 1px dashed var(--pc-glass-border); }
.bm-assert-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 2px; }
.bm-assert-badge { font-size: 10px; font-weight: 600; color: var(--pc-accent-green); background: rgba(34,197,94,0.1); padding: 2px 8px; border-radius: 10px; }
.bm-assert-row { display: flex; gap: 6px; align-items: center; }
.bm-assert-text { flex: 1; min-width: 0; }
.bm-assert-desc { flex: 1.6; min-width: 0; }

.bm-actions { display: flex; justify-content: space-between; align-items: center; padding-top: 4px; }

/* ── Progress ── */
.bm-progress { display: flex; align-items: center; gap: 10px; padding: 10px 14px; background: rgba(var(--pc-primary-rgb),0.05); border-radius: 8px; font-size: 12px; color: var(--pc-primary); }

/* ── Results: Case Cards ── */
.bm-results { display: flex; flex-direction: column; gap: 12px; }
.bm-result-card { background: var(--pc-bg-surface); border: 1px solid var(--pc-glass-border); border-radius: 10px; overflow: hidden; }
.bm-result-head { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: rgba(var(--pc-primary-rgb),0.04); border-bottom: 1px solid var(--pc-glass-border); }
.bm-result-prompt { font-size: 13px; font-weight: 500; color: var(--pc-text-primary); }
.bm-result-meta { display: flex; gap: 16px; padding: 6px 12px 10px; font-size: 11px; color: var(--pc-text-muted); font-variant-numeric: tabular-nums; }

/* ── Results: Grading Table ── */
.bm-grade-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.bm-grade-table th { padding: 6px 12px; text-align: left; font-size: 10px; font-weight: 600; color: var(--pc-text-muted); text-transform: uppercase; letter-spacing: 0.5px; background: rgba(var(--pc-primary-rgb),0.03); }
.bm-grade-table td { padding: 5px 12px; border-top: 1px solid var(--pc-glass-border); }
.bm-grade-text { cursor: help; }
.bm-grade-total td { font-weight: 700; font-size: 11px; border-top: 2px solid var(--pc-glass-border); }
.bm-pass { color: #22c55e; font-weight: 700; }
.bm-fail { color: #ef4444; }

/* ── Results: Stats Table ── */
.bm-stats-card { background: var(--pc-bg-surface); border: 1px solid var(--pc-glass-border); border-radius: 10px; padding: 12px 14px; }
.bm-stats-title { font-size: 13px; font-weight: 600; color: var(--pc-text-primary); margin-bottom: 8px; }
.bm-stats-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.bm-stats-table th { padding: 6px 10px; text-align: left; font-size: 10px; font-weight: 600; color: var(--pc-text-muted); text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid var(--pc-glass-border); }
.bm-stats-table td { padding: 7px 10px; border-bottom: 1px solid var(--pc-glass-border); }
.bm-stats-val { font-variant-numeric: tabular-nums; color: var(--pc-text-secondary); }
.bm-delta-up { color: #22c55e; font-weight: 700; }
.bm-delta-down { color: #ef4444; font-weight: 700; }

/* ── Results: LLM Summary Bar ── */
.bm-summary-bar { display: flex; gap: 20px; font-size: 12px; color: var(--pc-text-muted); padding: 8px 14px; background: var(--pc-bg-surface); border-radius: 8px; border: 1px solid var(--pc-glass-border);
  b { color: var(--pc-text-primary); }
  .up { color: #22c55e; font-weight: 600; }
  .down { color: #ef4444; font-weight: 600; }
}

.card-header-score {
  font-size: 14px;
  font-weight: 700;

  &.good { color: #22c55e; }
  &.bad { color: #ef4444; }
}

/* ── Optimize tab ── */
.bm-tab-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #22c55e; margin-left: 4px; vertical-align: middle; }
.bm-opt-page { display: flex; flex-direction: column; gap: 14px; }
.bm-opt-toggle { font-size: 12px; padding: 4px 12px; border: 1px solid var(--pc-glass-border); border-radius: 6px; background: var(--pc-bg-surface); color: var(--pc-text-secondary); cursor: pointer; }
.bm-opt-toggle:hover { color: var(--pc-primary); border-color: var(--pc-primary); }
.bm-opt-empty { display: flex; align-items: center; gap: 12px; padding: 14px 16px; background: var(--pc-bg-surface); border-radius: 8px; font-size: 13px; color: var(--pc-text-secondary); }
.bm-opt-source { font-size: 11px; color: var(--pc-text-muted); }
.bm-opt-editor { display: flex; flex-direction: column; gap: 10px; }
.bm-opt-actions { display: flex; align-items: center; gap: 10px; justify-content: flex-end; }
.bm-opt-diff-panes { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.bm-opt-diff-pane { background: var(--pc-bg-surface); border: 1px solid var(--pc-glass-border); border-radius: 8px; overflow: hidden; }
.bm-opt-diff-title { font-size: 12px; font-weight: 600; color: var(--pc-text-muted); padding: 8px 12px; border-bottom: 1px solid var(--pc-glass-border); }
.bm-opt-diff-content { padding: 10px 12px; margin: 0; font-size: 11.5px; font-family: 'Fira Code', 'Consolas', monospace; line-height: 1.6; white-space: pre-wrap; word-break: break-word; max-height: 500px; overflow-y: auto; color: var(--pc-text-primary); }
.diff-same { background: transparent; }
.diff-add { background: rgba(34,197,94,0.15); display: inline-block; width: 100%; }
.diff-remove { background: rgba(239,68,68,0.15); display: inline-block; width: 100%; }

.card-header-loading {
  font-size: 13px;
  color: var(--pc-primary);
  display: flex;
  align-items: center;
  gap: 6px;

  .el-icon {
    animation: spin 1s linear infinite;
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.dim-loading {
  opacity: 0.5;

  .dim-score {
    color: var(--pc-text-muted);
    font-size: 18px;
    font-weight: 700;
  }
}

/* ═══ Global polish: inputs, tables, cards, buttons ═══ */
:deep(.el-input__wrapper) {
  background: rgba(255,255,255,0.04) !important;
  border: 1px solid rgba(255,255,255,0.1) !important;
  border-radius: 6px !important;
  box-shadow: none !important;
}
:deep(.el-input__wrapper:hover) {
  border-color: rgba(255,255,255,0.18) !important;
  background: rgba(255,255,255,0.06) !important;
}
:deep(.el-input.is-focus .el-input__wrapper),
:deep(.el-input.is-disabled .el-input__wrapper) {
  border-color: var(--pc-primary) !important;
}
:deep(.el-textarea__inner) {
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 6px;
  color: var(--pc-text-primary);
  font-size: 13px;
  line-height: 1.6;
}
:deep(.el-textarea__inner:hover) {
  border-color: rgba(255,255,255,0.18);
  background: rgba(255,255,255,0.06);
}
:deep(.el-textarea__inner:focus) {
  border-color: var(--pc-primary);
  background: rgba(255,255,255,0.06);
}

/* ── Table polish ── */
.bm-grade-table th, .bm-stats-table th, .bm-assertion-table th {
  font-size: 10px; font-weight: 600; letter-spacing: 0.05em;
  text-transform: uppercase; color: var(--pc-text-muted);
  padding: 8px 12px; background: rgba(255,255,255,0.02);
}
.bm-grade-table td, .bm-stats-table td {
  font-size: 12px; padding: 7px 12px;
}
.bm-grade-table tr:hover td, .bm-stats-table tr:hover td {
  background: rgba(255,255,255,0.02);
}

/* ── Button polish ── */
.pc-glow-btn {
  border-radius: 8px; font-weight: 600; letter-spacing: 0.01em;
  transition: all 0.2s ease;
}
.pc-glow-btn.primary {
  background: var(--pc-primary); color: #fff; border: none;
  box-shadow: 0 0 20px rgba(var(--pc-primary-rgb), 0.2);
}
.pc-glow-btn.primary:hover {
  box-shadow: 0 0 30px rgba(var(--pc-primary-rgb), 0.35);
  transform: translateY(-1px);
}
.pc-glow-btn.secondary {
  background: rgba(255,255,255,0.08); color: var(--pc-text-secondary);
  border: 1px solid rgba(255,255,255,0.12);
}
.pc-glow-btn.secondary:hover {
  background: rgba(255,255,255,0.12); color: var(--pc-text-primary);
}

/* ── Left panel polish ── */
.left-panel {
  :deep(.el-select .el-input__wrapper) {
    border-radius: 8px !important;
  }
  :deep(.el-tree-node__content) {
    border-radius: 6px; padding: 3px 8px; margin: 1px 0;
    transition: background 0.15s;
  }
  :deep(.el-tree-node__content:hover) {
    background: rgba(255,255,255,0.06);
  }
  .content-viewer {
    border-radius: 8px;
  }
}

/* ── Score ring polish ── */
.score-ring {
  filter: drop-shadow(0 0 24px rgba(var(--pc-primary-rgb), 0.2));
  svg circle:first-child { stroke: rgba(255,255,255,0.06); }
  .ring-center .ring-value {
    font-size: 28px; font-weight: 800; letter-spacing: -0.02em;
  }
  .ring-center .ring-label {
    font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase;
  }
}

/* ── Tab polish ── */
.eval-tabs :deep(.el-tabs__item) {
  font-size: 13px; padding: 0 16px; height: 38px; line-height: 38px;
  transition: color 0.2s, background 0.2s;
}
.eval-tabs :deep(.el-tabs__item.is-active) {
  color: var(--pc-primary); font-weight: 600;
}

/* ── Collapse header polish ── */
.dashboard-card :deep(.el-collapse-item__header) {
  border-radius: 12px 12px 0 0; padding: 14px 18px;
  font-size: 14px; border-bottom: 1px solid var(--pc-glass-border);
}
</style>
