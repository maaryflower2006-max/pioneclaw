import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import SkillEval from '@/views/SkillEval.vue'
import zhCN from '@/locales/zh-CN'

// Mock Element Plus
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
  longApi: {
    post: vi.fn(),
  },
}))

// Mock echarts
vi.mock('echarts/core', () => ({ use: vi.fn(), init: vi.fn() }))
vi.mock('echarts/charts', () => ({ RadarChart: {}, LineChart: {} }))
vi.mock('echarts/components', () => ({
  TitleComponent: {}, TooltipComponent: {}, LegendComponent: {},
  GridComponent: {}, RadarComponent: {},
}))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

// Mock vue-echarts
vi.mock('vue-echarts', () => ({
  default: {
    name: 'VChart',
    template: '<div class="v-chart-mock"></div>',
    props: ['option', 'autoresize'],
  },
}))

// Mock marked
vi.mock('marked', () => ({
  marked: {
    parse: vi.fn((text: string) => `<p>${text}</p>`),
  },
}))

// Mock user store
vi.mock('@/stores/user', () => ({
  getAccessToken: vi.fn(() => 'test-token'),
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
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/skill-eval/skills') {
        return Promise.resolve({ data: mockSkills })
      }
      if (url.includes('/tree')) {
        return Promise.resolve({ data: { skill_name: 'test-skill', display_name: 'Test Skill', source: 'file', tree: mockFileTree } })
      }
      if (url.includes('/file')) {
        return Promise.resolve({ data: { path: 'SKILL.md', content: '# Test Skill\n\nThis is a test skill.', size: 50 } })
      }
      return Promise.resolve({ data: {} })
    })
    vi.mocked(api.post).mockResolvedValue({ data: {} })
  })

  it('should render the component without crashing', async () => {
    const wrapper = mount(SkillEval, { global: { plugins: [i18n] } })
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.find('.skill-eval-page').exists()).toBe(true)
  })

  it('should render left panel with all sub-panels', async () => {
    const wrapper = mount(SkillEval, { global: { plugins: [i18n] } })
    await flushPromises()
    expect(wrapper.find('.left-panel').exists()).toBe(true)
    expect(wrapper.find('.skill-selector').exists()).toBe(true)
    expect(wrapper.find('.file-tree-panel').exists()).toBe(true)
    expect(wrapper.find('.file-content-panel').exists()).toBe(true)
  })

  it('should fetch skills on mount and populate vm.skills', async () => {
    const wrapper = mount(SkillEval, { global: { plugins: [i18n] } })
    await flushPromises()
    expect(api.get).toHaveBeenCalledWith('/skill-eval/skills')
    expect((wrapper.vm as any).skills).toHaveLength(2)
  })

  it('should show placeholder when no skill is selected', async () => {
    const wrapper = mount(SkillEval, { global: { plugins: [i18n] } })
    await flushPromises()
    expect(wrapper.text()).toContain('Skill 评估与优化')
  })

  it('should handle API errors gracefully without crashing', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('Network Error'))
    const wrapper = mount(SkillEval, { global: { plugins: [i18n] } })
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.find('.skill-eval-page').exists()).toBe(true)
  })

  it('should load file tree and file content when skill is selected', async () => {
    const wrapper = mount(SkillEval, { global: { plugins: [i18n] } })
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.skills).toHaveLength(2)

    await vm.onSkillChange('test-skill')
    await flushPromises()

    expect(api.get).toHaveBeenCalledWith(expect.stringContaining('/tree'))
    expect(api.get).toHaveBeenCalledWith(expect.stringContaining('/file'), expect.any(Object))
  })
})
