import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import SkillEval from '@/views/SkillEval.vue'
import zhCN from '@/locales/zh-CN'

// Mock Element Plus (global plugin registered in setup.ts, but we need ElMessage mock)
vi.mock('element-plus', async () => {
  const actual = await vi.importActual('element-plus')
  return {
    ...actual,
    ElMessage: {
      success: vi.fn(),
      error: vi.fn(),
      warning: vi.fn(),
      info: vi.fn(),
    },
  }
})

// Mock the API module
vi.mock('@/api', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}))

// Mock echarts - canvas rendering doesn't work in happy-dom
vi.mock('echarts/core', () => ({
  use: vi.fn(),
  init: vi.fn(),
}))
vi.mock('echarts/charts', () => ({
  RadarChart: {},
  LineChart: {},
}))
vi.mock('echarts/components', () => ({
  TitleComponent: {},
  TooltipComponent: {},
  LegendComponent: {},
  GridComponent: {},
  RadarComponent: {},
}))
vi.mock('echarts/renderers', () => ({
  CanvasRenderer: {},
}))

// Mock vue-echarts
vi.mock('vue-echarts', () => ({
  default: {
    name: 'VChart',
    template: '<div class="v-chart-mock"></div>',
    props: ['option', 'autoresize'],
  },
}))

// Mock marked (so it doesn't fail on malformed content)
vi.mock('marked', () => ({
  marked: {
    parse: vi.fn((text: string) => `<p>${text}</p>`),
  },
}))

import { api } from '@/api'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': zhCN },
})

const mockSkills = [
  { name: 'test-skill', display_name: 'Test Skill', description: 'A test skill', source: 'file', scope: 'system', enabled: true, skill_format: 'inline' },
  { name: 'db-skill', display_name: 'DB Skill', description: 'From DB', source: 'db', scope: 'org', enabled: true, skill_format: 'inline', id: 1 },
]

const mockFileTree = [
  { name: 'SKILL.md', path: 'SKILL.md', type: 'file', size: 2048 },
  { name: 'scripts', path: 'scripts', type: 'dir', children: [
    { name: 'run.py', path: 'scripts/run.py', type: 'file', size: 512 },
  ]},
]

describe('SkillEval.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Default: return empty skills list
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/skill-eval/skills') {
        return Promise.resolve({ data: mockSkills })
      }
      if (url.includes('/tree')) {
        return Promise.resolve({
          data: {
            skill_name: 'test-skill',
            display_name: 'Test Skill',
            source: 'file',
            tree: mockFileTree,
          },
        })
      }
      if (url.includes('/file')) {
        return Promise.resolve({
          data: { path: 'SKILL.md', content: '# Test Skill\n\nThis is a test skill.', size: 50 },
        })
      }
      return Promise.resolve({ data: {} })
    })
  })

  // ── Basic render tests ──

  it('should render the component without crashing', async () => {
    const wrapper = mount(SkillEval, {
      global: { plugins: [i18n] },
    })

    await flushPromises()

    expect(wrapper.exists()).toBe(true)
    expect(wrapper.find('.skill-eval-page').exists()).toBe(true)
  })

  // ── Left panel tests ──

  it('should render the left panel with skill selector, file tree, and content viewer', async () => {
    const wrapper = mount(SkillEval, {
      global: { plugins: [i18n] },
    })

    await flushPromises()

    // Left panel exists
    expect(wrapper.find('.left-panel').exists()).toBe(true)

    // Skill selector (el-select) exists
    expect(wrapper.find('.skill-selector').exists()).toBe(true)

    // File tree panel exists
    expect(wrapper.find('.file-tree-panel').exists()).toBe(true)

    // Content viewer panel exists
    expect(wrapper.find('.file-content-panel').exists()).toBe(true)
  })

  it('should fetch skills on mount and display them in the selector', async () => {
    const wrapper = mount(SkillEval, {
      global: { plugins: [i18n] },
    })

    await flushPromises()

    expect(api.get).toHaveBeenCalledWith('/skill-eval/skills')

    // Dropdown options should contain skill names
    const text = wrapper.text()
    expect(text).toContain('Test Skill')
    expect(text).toContain('DB Skill')
  })

  // ── Right panel tests ──

  it('should show placeholder in right panel when no skill is selected', async () => {
    const wrapper = mount(SkillEval, {
      global: { plugins: [i18n] },
    })

    await flushPromises()

    // Placeholder should be visible when no skill selected
    const text = wrapper.text()
    expect(text).toContain('Skill 评估与优化')
  })

  // ── Skill selection tests ──

  it('should load file tree when a skill is selected', async () => {
    const wrapper = mount(SkillEval, {
      global: { plugins: [i18n] },
    })

    await flushPromises()

    // Simulate selecting a skill by triggering the select component's change
    // Since el-select is complex, we use vm method directly
    const vm = wrapper.vm as any
    await vm.onSkillChange('test-skill')
    await flushPromises()

    // Should have called tree and file API
    expect(api.get).toHaveBeenCalledWith(expect.stringContaining('/tree'))
    expect(api.get).toHaveBeenCalledWith(expect.stringContaining('/file'))
  })

  it('should render the right panel with 3 tabs after skill selection', async () => {
    const wrapper = mount(SkillEval, {
      global: { plugins: [i18n] },
    })

    await flushPromises()

    const vm = wrapper.vm as any
    await vm.onSkillChange('test-skill')
    await flushPromises()

    // Right panel should now contain the tabs
    expect(wrapper.find('.eval-tabs').exists()).toBe(true)

    const text = wrapper.text()
    expect(text).toContain('评估结果')
    expect(text).toContain('优化建议')
    expect(text).toContain('历史记录')
  })

  // ── Evaluation tests ──

  it('should have a mode selector with 3 options', async () => {
    const wrapper = mount(SkillEval, {
      global: { plugins: [i18n] },
    })

    await flushPromises()

    const vm = wrapper.vm as any
    await vm.onSkillChange('test-skill')
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('静态检查')
    expect(text).toContain('LLM 评分')
    expect(text).toContain('完整评估')
  })

  it('should call evaluate API with selected mode on runEvaluation', async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: {
        id: 1,
        overall_score: 85,
        dimensions: [
          { key: 'frontmatter', label: 'Frontmatter', score: 8, max_score: 10, comment: 'Good', evidence: '' },
        ],
        static_checks: [],
        redflag_hits: [],
        suggestions: [],
        summary: 'Good skill',
        model_used: 'test-model',
        tokens_used: 100,
        eval_type: 'llm',
        eval_mode: 'evaluate',
      },
    })

    const wrapper = mount(SkillEval, {
      global: { plugins: [i18n] },
    })

    await flushPromises()

    const vm = wrapper.vm as any
    await vm.onSkillChange('test-skill')
    await flushPromises()

    // Change mode to llm
    vm.evalMode = 'llm'
    await vm.runEvaluation()
    await flushPromises()

    // Should have called evaluate API with mode=llm as query param
    expect(api.post).toHaveBeenCalledWith(
      expect.stringContaining('/evaluate'),
      expect.any(Object),
      expect.objectContaining({ params: { mode: 'llm' } }),
    )

    // Should display evaluation result
    expect(wrapper.text()).toContain('综合评分')
  })

  it('should display radar chart zone after evaluation', async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: {
        id: 1,
        overall_score: 78.5,
        dimensions: [
          { key: 'frontmatter', label: 'Frontmatter', score: 7, max_score: 10, comment: 'OK', evidence: '' },
          { key: 'workflow', label: '工作流', score: 8, max_score: 10, comment: 'Good', evidence: '' },
        ],
        static_checks: [],
        redflag_hits: [],
        suggestions: [],
        summary: 'Decent skill',
        model_used: '',
        tokens_used: 0,
        eval_type: 'static',
        eval_mode: 'evaluate',
      },
    })

    const wrapper = mount(SkillEval, {
      global: { plugins: [i18n] },
    })

    await flushPromises()

    const vm = wrapper.vm as any
    await vm.onSkillChange('test-skill')
    await flushPromises()
    await vm.runEvaluation()
    await flushPromises()

    // Should display the overall score and radar chart
    expect(wrapper.text()).toContain('维度雷达图')
  })

  // ── History tab tests ──

  it('should load history when switching to history tab', async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/skill-eval/skills') {
        return Promise.resolve({ data: mockSkills })
      }
      if (url.includes('/tree')) {
        return Promise.resolve({ data: { skill_name: 'test-skill', source: 'file', tree: mockFileTree } })
      }
      if (url.includes('/file')) {
        return Promise.resolve({ data: { path: 'SKILL.md', content: 'test', size: 4 } })
      }
      if (url.includes('/history')) {
        return Promise.resolve({
          data: {
            items: [
              { id: 1, skill_name: 'test-skill', eval_type: 'llm', eval_mode: 'evaluate', overall_score: 85, dimensions: [], summary: 'Good', model_used: 'm1', tokens_used: 100, created_at: '2024-01-01T00:00:00Z' },
            ],
            total: 1,
            page: 1,
            page_size: 10,
          },
        })
      }
      return Promise.resolve({ data: {} })
    })

    const wrapper = mount(SkillEval, {
      global: { plugins: [i18n] },
    })

    await flushPromises()

    const vm = wrapper.vm as any
    await vm.onSkillChange('test-skill')
    await flushPromises()

    // Switch to history tab
    await vm.onTabChange('history')
    await flushPromises()

    // Should have called history API
    expect(api.get).toHaveBeenCalledWith(expect.stringContaining('/history'))
  })

  // ── Error handling tests ──

  it('should handle API errors gracefully without crashing', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('Network Error'))

    const wrapper = mount(SkillEval, {
      global: { plugins: [i18n] },
    })

    await flushPromises()

    // Component should still render
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.find('.skill-eval-page').exists()).toBe(true)
  })

  // ── Optimize tab tests ──

  it('should render optimize button in optimize tab', async () => {
    const wrapper = mount(SkillEval, {
      global: { plugins: [i18n] },
    })

    await flushPromises()

    const vm = wrapper.vm as any
    await vm.onSkillChange('test-skill')
    await flushPromises()

    // Switch to optimize tab
    await vm.onTabChange('optimize')
    await flushPromises()

    // Should show the optimize hint
    expect(wrapper.text()).toContain('生成优化方案')
  })

  it('should call optimize API and display result', async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: {
        optimized_content: '# Optimized Skill',
        original_content: '# Original',
        changes: [{ dimension: 'structure', description: 'Improved structure' }],
        estimated_score_delta: 5.5,
        diff_text: '@@ -1,1 +1,1 @@\n-# Original\n+# Optimized Skill',
        eval_id: 1,
      },
    })

    const wrapper = mount(SkillEval, {
      global: { plugins: [i18n] },
    })

    await flushPromises()

    const vm = wrapper.vm as any
    await vm.onSkillChange('test-skill')
    await flushPromises()

    await vm.runOptimize()
    await flushPromises()

    // Should have called optimize API
    expect(api.post).toHaveBeenCalledWith(
      expect.stringContaining('/optimize'),
      expect.objectContaining({ content: expect.any(String) }),
    )

    // Should display score delta and diff
    expect(wrapper.text()).toContain('+5.5')
    expect(wrapper.text()).toContain('Improved structure')
  })

  // ── Discard optimization test ──

  it('should discard optimization result and show button again', async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: {
        optimized_content: '# Optimized Skill',
        original_content: '# Original',
        changes: [],
        estimated_score_delta: 0,
        diff_text: '',
        eval_id: 1,
      },
    })

    const wrapper = mount(SkillEval, {
      global: { plugins: [i18n] },
    })

    await flushPromises()

    const vm = wrapper.vm as any
    await vm.onSkillChange('test-skill')
    await flushPromises()
    await vm.runOptimize()
    await flushPromises()

    // Should have the optimized content
    expect(vm.optimizedContent).toBe('# Optimized Skill')

    // Discard
    await vm.discardOptimization()
    await flushPromises()

    // Should be cleared
    expect(vm.optimizedContent).toBe('')
    expect(vm.diffText).toBe('')
  })

  // ── Skill change resets evaluation state ──

  it('should reset evaluation when switching skills', async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: {
        id: 1,
        overall_score: 90,
        dimensions: [],
        static_checks: [],
        redflag_hits: [],
        suggestions: [],
        summary: '',
        model_used: '',
        tokens_used: 0,
        eval_type: 'static',
        eval_mode: 'evaluate',
      },
    })

    const wrapper = mount(SkillEval, {
      global: { plugins: [i18n] },
    })

    await flushPromises()

    const vm = wrapper.vm as any
    await vm.onSkillChange('test-skill')
    await flushPromises()
    await vm.runEvaluation()
    await flushPromises()

    expect(vm.evaluation).not.toBeNull()

    // Switch to another skill
    await vm.onSkillChange('db-skill')
    await flushPromises()

    // Should reset evaluation
    expect(vm.evaluation).toBeNull()
    expect(vm.historyItems).toEqual([])
    expect(vm.historyTotal).toBe(0)
  })
})
