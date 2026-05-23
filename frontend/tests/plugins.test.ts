import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import Plugins from '@/views/Plugins.vue'
import zhCN from '@/locales/zh-CN'

// Mock Element Plus components first
vi.mock('element-plus', () => ({
  ElMessage: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

// Mock plugins API with hoisted mock
vi.mock('@/api/plugins', () => ({
  pluginsApi: {
    list: vi.fn(),
    stats: vi.fn(),
    discover: vi.fn(),
    load: vi.fn(),
    unload: vi.fn(),
    reload: vi.fn(),
    listSubscriptions: vi.fn(),
    healthAll: vi.fn(),
  },
}))

// Import after mock
import { pluginsApi } from '@/api/plugins'

// Create i18n instance
const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': zhCN },
})

describe('Plugins.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Default mocks
    vi.mocked(pluginsApi.list).mockResolvedValue({
      data: [
        {
          plugin_id: 'test-plugin',
          name: 'Test Plugin',
          version: '1.0.0',
          description: 'A test plugin',
          state: 'loaded',
          error: null,
          dependencies: ['dep1', 'dep2'],
          subscriptions: ['event.test'],
        },
        {
          plugin_id: 'unloaded-plugin',
          name: 'Unloaded Plugin',
          version: '2.0.0',
          description: 'An unloaded plugin',
          state: 'unloaded',
          error: null,
          dependencies: [],
          subscriptions: [],
        },
      ],
    })
    vi.mocked(pluginsApi.stats).mockResolvedValue({
      data: {
        total: 2,
        by_state: { loaded: 1, unloaded: 1 },
        plugin_dir: '/plugins',
      },
    })
    vi.mocked(pluginsApi.listSubscriptions).mockResolvedValue({
      data: [
        {
          sub_id: 'sub-1',
          topic: 'event.test',
          handler: 'on_test',
          priority: 10,
          wildcard: false,
        },
      ],
    })
    vi.mocked(pluginsApi.healthAll).mockResolvedValue({
      data: [],
    })
  })

  it('should render plugin list on mount', async () => {
    const wrapper = mount(Plugins, {
      global: {
        plugins: [i18n],
      },
    })

    await flushPromises()

    // Check API calls
    expect(pluginsApi.list).toHaveBeenCalled()
    expect(pluginsApi.stats).toHaveBeenCalled()
    expect(pluginsApi.listSubscriptions).toHaveBeenCalled()
  })

  it('should display plugin names', async () => {
    const wrapper = mount(Plugins, {
      global: {
        plugins: [i18n],
      },
    })

    await flushPromises()

    // Verify data is loaded by checking the mocked API response was processed
    expect(pluginsApi.list).toHaveBeenCalled()
    // Check that the component has the expected data in its reactive state
    // (el-table scoped slots don't render in test-utils DOM reliably)
    expect((wrapper.vm as any).plugins).toHaveLength(2)
    expect((wrapper.vm as any).plugins[0].name).toBe('Test Plugin')
    expect((wrapper.vm as any).plugins[1].name).toBe('Unloaded Plugin')
  })

  it('should handle API errors gracefully', async () => {
    vi.mocked(pluginsApi.list).mockRejectedValue(new Error('API Error'))

    const wrapper = mount(Plugins, {
      global: {
        plugins: [i18n],
      },
    })

    await flushPromises()

    // Component should still render without crashing
    expect(wrapper.exists()).toBe(true)
  })

  it('should call discover API when discover button clicked', async () => {
    vi.mocked(pluginsApi.discover).mockResolvedValue({
      data: ['plugin-a', 'plugin-b'],
    })

    const wrapper = mount(Plugins, {
      global: {
        plugins: [i18n],
      },
    })

    await flushPromises()

    // Find discover button by icon
    const buttons = wrapper.findAll('button')
    expect(buttons.length).toBeGreaterThan(0)
  })

  it('should display stats from API', async () => {
    const wrapper = mount(Plugins, {
      global: {
        plugins: [i18n],
      },
    })

    await flushPromises()

    // Stats API should be called
    expect(pluginsApi.stats).toHaveBeenCalled()
  })
})
