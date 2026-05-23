<template>
  <div class="skills-page">
    <div class="pc-page-header">
      <h2 class="pc-page-title">{{ $t('skill.title') }}</h2>
      <div class="header-actions">
        <button class="pc-glow-btn secondary" @click="reloadSkills" :disabled="reloading">
          <el-icon><Refresh /></el-icon>
          {{ $t('skill.hotReload') }}
        </button>
        <button class="pc-glow-btn secondary" @click="showSchemaDialog = true">
          <el-icon><Setting /></el-icon>
          {{ $t('skill.schemaManager') }}
        </button>
        <button class="pc-glow-btn" @click="showCreateDialog()">
          <el-icon><Plus /></el-icon>
          {{ $t('skill.create') }}
        </button>
      </div>
    </div>

    <!-- Stat Cards -->
    <div class="skill-stats">
      <el-card class="stat-card">
        <div class="stat-icon total">
          <el-icon><Cpu /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ skills.length }}</div>
          <div class="stat-label">{{ $t('skill.total') }}</div>
        </div>
      </el-card>
      <el-card class="stat-card">
        <div class="stat-icon active">
          <el-icon><Check /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ activeCount }}</div>
          <div class="stat-label">{{ $t('skill.activeCount') }}</div>
        </div>
      </el-card>
      <el-card class="stat-card">
        <div class="stat-icon configured">
          <el-icon><Key /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ configuredCount }}</div>
          <div class="stat-label">{{ $t('skill.configured') }}</div>
        </div>
      </el-card>
      <el-card class="stat-card">
        <div class="stat-icon system">
          <el-icon><Tools /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ schemaCount }}</div>
          <div class="stat-label">{{ $t('skill.hasSchema') }}</div>
        </div>
      </el-card>
    </div>

    <!-- Skill List -->
    <el-card class="skills-card">
      <el-table :data="skills" v-loading="loading" style="width: 100%" class="pc-data-table">
        <template #empty>
          <el-empty :description="$t('common.noData')" />
        </template>
        <el-table-column prop="name" :label="$t('common.name')" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="skill-name-cell">
              <span class="skill-name">{{ row.name }}</span>
              <el-tag v-if="row.isFileSkill" size="small" type="success" effect="plain">
                文件
              </el-tag>
              <el-tag v-if="row.always_activate" size="small" type="danger" effect="dark">
                AUTO
              </el-tag>
              <el-tag v-if="row.skill_format === 'yaml'" size="small" type="warning">
                YAML
              </el-tag>
              <el-tag v-if="row._scope" size="small" :type="getScopeType(row._scope)">
                {{ getScopeLabel(row._scope) }}
              </el-tag>
              <el-tag v-if="pendingApprovalSkillIds.has(row.id) && row._scope === 'user'" size="small" type="warning">
                已提交
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="metadata.description" :label="$t('common.description')" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.metadata?.description || row.metadata?.title || $t('common.noData') }}
          </template>
        </el-table-column>
        <el-table-column :label="$t('common.status')" width="80" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" @change="toggleSkill(row)" size="small" :disabled="row.isFileSkill" />
          </template>
        </el-table-column>
        <el-table-column :label="$t('skill.config')" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="getConfigStatusType(row.configStatus)" size="small">
              {{ getConfigStatusText(row.configStatus) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="$t('skill.deps')" width="80" align="center">
          <template #default="{ row }">
            <template v-if="row.dependencies && Object.keys(row.dependencies).length > 0">
              <el-button size="small" text type="primary" @click="checkDependencies(row)">
                <el-icon><Warning /></el-icon>
                {{ $t('skill.check') }}
              </el-button>
            </template>
            <template v-else>
              <span class="text-muted-sm">{{ $t('skill.none') }}</span>
            </template>
          </template>
        </el-table-column>
        <el-table-column :label="$t('common.actions')" width="250" align="center">
          <template #default="{ row }">
            <div class="pc-action-group">
              <el-button size="small" @click="showEditDialog(row)" :title="$t('common.edit')">
                <el-icon><Edit /></el-icon>
              </el-button>
              <el-button size="small" type="primary" @click="showConfigDialog(row)" :disabled="row.isFileSkill" title="配置">
                <el-icon><Setting /></el-icon>
              </el-button>
              <el-button v-if="!row.isFileSkill && row._scope === 'user' && row.creator_id === userStore.user?.id && !pendingApprovalSkillIds.has(row.id) && !userStore.isSuperAdmin" size="small" type="success" @click="showSubmitDialog(row)" title="提交评审">
                <el-icon><Upload /></el-icon>
              </el-button>
              <el-button v-if="row.isFileSkill && (userStore.isSuperAdmin || userStore.isOrgAdmin)" size="small" type="success" @click="publishFileSkill(row)" title="发布到系统">
                <el-icon><Upload /></el-icon>
              </el-button>
              <el-button size="small" type="danger" @click="deleteSkill(row)" :title="$t('common.delete')">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Create/Edit Skill Dialog -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingSkill ? $t('skill.edit') : $t('skill.create')"
      width="800px"
      destroy-on-close
      class="cyber-dialog"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item :label="$t('common.name')" prop="name">
              <el-input v-model="form.name" :placeholder="$t('skill.uniqueSkillId')" :disabled="!!editingSkill" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="$t('skill.displayName')" prop="title">
              <el-input v-model="form.title" :placeholder="$t('skill.displayName')" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item :label="$t('common.description')" prop="description">
          <el-input v-model="form.description" type="textarea" :rows="2" :placeholder="$t('skill.skillDescription')" />
        </el-form-item>
        <el-form-item :label="$t('skill.tags')" prop="tags">
          <el-select v-model="form.tags" multiple filterable allow-create :placeholder="$t('skill.selectOrCreateTags')" style="width: 100%">
            <el-option :label="$t('skill.autoLoad')" value="auto" />
            <el-option :label="$t('skill.tool')" value="tool" />
            <el-option :label="$t('skill.knowledge')" value="knowledge" />
            <el-option :label="$t('skill.workflow')" value="workflow" />
          </el-select>
        </el-form-item>
        <el-form-item :label="$t('skill.autoLoad')">
          <el-switch v-model="form.auto_load" />
          <span class="form-hint">{{ $t('skill.agentAutoLoads') }}</span>
        </el-form-item>
        <el-form-item :label="$t('skill.format')">
          <el-select v-model="form.skill_format" style="width: 200px">
            <el-option :label="$t('skill.inline')" value="inline" />
            <el-option :label="$t('skill.yamlFrontmatter')" value="yaml" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="userStore.isSuperAdmin || userStore.isOrgAdmin" label="可见范围">
          <el-select v-model="form.scope" style="width: 200px">
            <el-option label="本地" value="user" />
            <el-option label="组织" value="org" />
            <el-option v-if="userStore.isSuperAdmin" label="系统" value="system" />
          </el-select>
          <span class="form-hint">{{ userStore.isSuperAdmin ? '超管可直接创建系统级技能' : '组织管理员可直接创建组织级技能' }}</span>
        </el-form-item>

        <!-- 内容输入方式选择 -->
        <el-form-item :label="$t('skill.content')" prop="content">
          <div class="content-input-method">
            <el-radio-group v-model="contentInputMethod" style="margin-bottom: 12px">
              <el-radio value="paste">{{ $t('skill.pasteContent') }}</el-radio>
              <el-radio value="upload">{{ $t('skill.uploadPackage') }}</el-radio>
            </el-radio-group>

            <!-- 直接粘贴内容 -->
            <el-input
              v-if="contentInputMethod === 'paste'"
              v-model="form.content"
              type="textarea"
              :rows="12"
              :placeholder="$t('skill.skillContent')"
              class="monospace-input"
            />

            <!-- 上传压缩包 -->
            <div v-else class="upload-area">
              <el-upload
                ref="skillUploadRef"
                :auto-upload="false"
                :show-file-list="true"
                :limit="1"
                accept=".zip"
                :on-change="handleSkillPackageChange"
                drag
              >
                <el-icon class="el-icon--upload"><Upload /></el-icon>
                <div class="el-upload__text">
                  {{ $t('skill.dropZipOrClick') }}
                </div>
                <template #tip>
                  <div class="el-upload__tip">{{ $t('skill.zipTip') }}</div>
                </template>
              </el-upload>
              <div v-if="uploadedFileName" class="uploaded-info">
                <el-tag type="success">{{ $t('skill.packageLoaded') }}: {{ uploadedFileName }}</el-tag>
              </div>
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ $t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit" class="cyber-btn primary-glow">
          {{ editingSkill ? $t('skill.update') : $t('common.create') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- Skill Config Dialog -->
    <el-dialog
      v-model="configDialogVisible"
      :title="`${configSkill?.name} - ${$t('skill.configuration')}`"
      width="700px"
      destroy-on-close
      class="cyber-dialog"
    >
      <div v-if="configSchema" class="config-form">
        <!-- Config status alert -->
        <el-alert
          v-if="configStatus && configStatus.status !== 'valid'"
          :title="getConfigAlertTitle(configStatus.status)"
          :type="configStatus.status === 'not_configured' ? 'info' : 'warning'"
          :closable="false"
          show-icon
          style="margin-bottom: 16px"
        />

        <!-- Dynamic config form -->
        <el-form ref="configFormRef" :model="configForm" label-width="140px">
          <template v-for="field in configSchema.fields" :key="field.key">
            <!-- Object type (collapsible) -->
            <template v-if="field.type === 'object'">
              <el-divider content-position="left">
                <el-checkbox v-model="objectExpanded[field.key]" />
                {{ field.label }}
              </el-divider>
              <div v-show="objectExpanded[field.key]" class="object-fields">
                <template v-for="subField in field.fields" :key="subField.key">
                  <FormField
                    :field="subField"
                    v-model="configForm[field.key][subField.key]"
                  />
                </template>
              </div>
            </template>
            <!-- Regular field -->
            <template v-else>
              <FormField
                :field="field"
                v-model="configForm[field.key]"
              />
            </template>
          </template>
        </el-form>
      </div>
      <el-empty v-else :description="$t('skill.noConfigSchema')" />

      <template #footer>
        <el-button @click="resetConfig">{{ $t('skill.reset') }}</el-button>
        <el-button type="warning" @click="fixConfig" v-if="configStatus?.status === 'missing_fields'">
          {{ $t('skill.autoFix') }}
        </el-button>
        <el-button type="primary" :loading="savingConfig" @click="saveConfig" class="cyber-btn primary-glow">
          {{ $t('skill.saveConfig') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- Schema Manager Dialog -->
    <el-dialog v-model="showSchemaDialog" :title="$t('skill.schemaManager')" width="900px" destroy-on-close class="cyber-dialog">
      <el-tabs>
        <el-tab-pane :label="$t('skill.createSchema')">
          <el-form ref="schemaFormRef" :model="schemaForm" label-width="100px">
            <el-form-item :label="$t('skill.skillName')" required>
              <el-input v-model="schemaForm.skill_name" :placeholder="$t('skill.skillName')" />
            </el-form-item>
            <el-form-item :label="$t('skill.version')">
              <el-input v-model="schemaForm.version" placeholder="1.0.0" />
            </el-form-item>
            <el-form-item :label="$t('common.description')">
              <el-input v-model="schemaForm.description" type="textarea" :rows="2" />
            </el-form-item>
            <el-form-item :label="$t('skill.fieldDefinition')">
              <el-input
                v-model="schemaForm.fieldsJson"
                type="textarea"
                :rows="15"
                :placeholder="$t('skill.jsonFieldDefs')"
                class="monospace-input"
              />
            </el-form-item>
          </el-form>
          <el-button type="primary" @click="createSchema" class="cyber-btn primary-glow">{{ $t('skill.createSchema') }}</el-button>
        </el-tab-pane>
        <el-tab-pane :label="$t('skill.fieldTemplates')">
          <div class="schema-templates">
            <el-card v-for="template in fieldTemplates" :key="template.name" class="template-card">
              <div class="template-header">
                <span class="template-name">{{ template.name }}</span>
                <el-tag size="small">{{ template.type }}</el-tag>
              </div>
              <pre class="template-code">{{ template.code }}</pre>
              <el-button size="small" @click="copyTemplate(template.code)" class="cyber-btn ghost">{{ $t('skill.copy') }}</el-button>
            </el-card>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-dialog>

    <!-- 提交评审对话框 -->
    <el-dialog v-model="submitDialogVisible" title="提交评审" width="520px" class="submit-review-dialog">
      <div v-if="submittingSkill" class="submit-review-body">
        <p class="submit-intro">
          将技能 <strong class="skill-highlight">{{ submittingSkill.display_name || submittingSkill.name }}</strong> 从
          <el-tag size="small" type="info">本地</el-tag> 提升为：
        </p>
        <div class="scope-cards">
          <div
            v-if="!userStore.isOrgAdmin"
            class="scope-card"
            :class="{ selected: targetScope === 'org' }"
            @click="targetScope = 'org'"
          >
            <div class="scope-card-icon org-icon">
              <el-icon :size="28"><OfficeBuilding /></el-icon>
            </div>
            <div class="scope-card-body">
              <div class="scope-card-title">
                <el-tag type="warning" size="small">组织</el-tag>
              </div>
              <p class="scope-card-desc">提交到组织级别，同组织成员审核通过后可用</p>
            </div>
            <div v-if="targetScope === 'org'" class="scope-card-check">
              <el-icon><Check /></el-icon>
            </div>
          </div>
          <div
            class="scope-card"
            :class="{ selected: targetScope === 'system' }"
            @click="targetScope = 'system'"
          >
            <div class="scope-card-icon sys-icon">
              <el-icon :size="28"><Monitor /></el-icon>
            </div>
            <div class="scope-card-body">
              <div class="scope-card-title">
                <el-tag type="danger" size="small">系统</el-tag>
              </div>
              <p class="scope-card-desc">提交到系统级别，审核通过后全局可见</p>
            </div>
            <div v-if="targetScope === 'system'" class="scope-card-check">
              <el-icon><Check /></el-icon>
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="submitDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForReview" :loading="submitting" class="cyber-btn primary-glow">
          提交评审
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { api } from '@/api'
import { useUserStore } from '@/stores/user'
import { Cpu, Check, Key, Tools, Plus, Edit, Delete, Setting, Refresh, Warning, Upload, OfficeBuilding, Monitor } from '@element-plus/icons-vue'

const { t: $t } = useI18n()
const userStore = useUserStore()

// Form field component
const FormField = {
  props: ['field', 'modelValue'],
  emits: ['update:modelValue'],
  template: `
    <el-form-item :label="field.label" :required="field.required">
      <template v-if="field.type === 'string'">
        <el-input
          :model-value="modelValue"
          @update:model-value="$emit('update:modelValue', $event)"
          :placeholder="field.placeholder"
        />
      </template>
      <template v-else-if="field.type === 'password'">
        <el-input
          :model-value="modelValue"
          @update:model-value="$emit('update:modelValue', $event)"
          type="password"
          show-password
          :placeholder="field.placeholder"
        />
      </template>
      <template v-else-if="field.type === 'number'">
        <el-input-number
          :model-value="modelValue"
          @update:model-value="$emit('update:modelValue', $event)"
          :min="field.min"
          :max="field.max"
          style="width: 100%"
        />
      </template>
      <template v-else-if="field.type === 'boolean'">
        <el-switch
          :model-value="modelValue"
          @update:model-value="$emit('update:modelValue', $event)"
        />
      </template>
      <template v-else-if="field.type === 'select'">
        <el-select
          :model-value="modelValue"
          @update:model-value="$emit('update:modelValue', $event)"
          style="width: 100%"
        >
          <el-option
            v-for="opt in field.options"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
      </template>
      <template v-else-if="field.type === 'email'">
        <el-input
          :model-value="modelValue"
          @update:model-value="$emit('update:modelValue', $event)"
          type="email"
          :placeholder="field.placeholder"
        />
      </template>
      <div v-if="field.description" class="field-desc">{{ field.description }}</div>
    </el-form-item>
  `
}

interface Skill {
  id: number
  name: string
  display_name?: string
  description?: string
  content?: string
  path?: string
  enabled: boolean
  source: string
  auto_load: boolean
  _source?: string
  _scope?: string
  isFileSkill?: boolean
  creator_id?: number
  always_activate?: boolean
  skill_format?: string
  scope?: string
  is_active?: boolean
  metadata: {
    title: string
    description: string
    tags: string[]
    always: boolean
  }
  hasSchema?: boolean
  configStatus?: string
}

interface Schema {
  skill_name: string
  version: string
  description: string
  fields: any[]
}

const loading = ref(false)
const reloading = ref(false)
const skills = ref<Skill[]>([])

// Dialogs
const dialogVisible = ref(false)
const configDialogVisible = ref(false)
const showSchemaDialog = ref(false)
const submitDialogVisible = ref(false)
const editingSkill = ref<Skill | null>(null)
const submitting = ref(false)
const savingConfig = ref(false)
const submittingSkill = ref<Skill | null>(null)
const targetScope = ref<string>('org')
const pendingApprovalSkillIds = ref<Set<number>>(new Set())

// 内容输入方式
const contentInputMethod = ref<'paste' | 'upload'>('paste')
const skillUploadRef = ref()
const uploadedFileName = ref('')

// Skill form
const formRef = ref()
const form = reactive({
  name: '',
  title: '',
  description: '',
  tags: [] as string[],
  auto_load: false,
  skill_format: 'inline',
  scope: 'user',
  content: ''
})

const rules = {
  name: [{ required: true, message: $t('skill.enterName'), trigger: 'blur' }]
}

// Config related
const configSkill = ref<Skill | null>(null)
const configSchema = ref<Schema | null>(null)
const configForm = ref<Record<string, any>>({})
const configStatus = ref<any>(null)
const objectExpanded = ref<Record<string, boolean>>({})

// Schema form
const schemaForm = reactive({
  skill_name: '',
  version: '1.0.0',
  description: '',
  fieldsJson: ''
})

// Field templates
const fieldTemplates = [
  {
    name: 'API Key',
    type: 'password',
    code: `{
  "key": "api_key",
  "type": "password",
  "label": "API Key",
  "description": "API key",
  "required": true,
  "sensitive": true,
  "placeholder": "Enter API Key"
}`
  },
  {
    name: 'API URL',
    type: 'string',
    code: `{
  "key": "base_url",
  "type": "string",
  "label": "API URL",
  "description": "API service endpoint",
  "placeholder": "https://api.example.com"
}`
  },
  {
    name: 'Timeout',
    type: 'number',
    code: `{
  "key": "timeout",
  "type": "number",
  "label": "Timeout (sec)",
  "default": 30,
  "min": 5,
  "max": 300
}`
  },
  {
    name: 'Email Config',
    type: 'object',
    code: `{
  "key": "email_config",
  "type": "object",
  "label": "Email Config",
  "collapsible": true,
  "fields": [
    {
      "key": "email",
      "type": "email",
      "label": "Email Address",
      "required": true
    },
    {
      "key": "password",
      "type": "password",
      "label": "Auth Password",
      "required": true,
      "sensitive": true
    }
  ]
}`
  }
]

// Computed
const activeCount = computed(() => skills.value.filter(s => s.enabled).length)
const configuredCount = computed(() => skills.value.filter(s => s.configStatus === 'valid').length)
const schemaCount = computed(() => skills.value.filter(s => s.hasSchema).length)

// Methods
function getScopeLabel(scope: string): string {
  const labels: Record<string, string> = {
    user: '本地', personal: '本地',
    org: '组织',
    system: '系统', public: '系统'
  }
  return labels[scope] || scope
}

function getScopeType(scope: string): string {
  const types: Record<string, string> = {
    user: 'info',
    org: 'warning',
    system: 'danger'
  }
  return types[scope] || 'info'
}

async function showSubmitDialog(skill: Skill) {
  submittingSkill.value = skill
  targetScope.value = userStore.isOrgAdmin ? 'system' : 'org'
  submitDialogVisible.value = true
}

async function submitForReview() {
  if (!submittingSkill.value) return
  submitting.value = true
  try {
    const skill = submittingSkill.value
    await api.post('/approvals', {
      approval_type: targetScope.value === 'system' ? 'skill_to_system' : 'skill_to_org',
      title: `技能评审: ${skill.display_name || skill.name}`,
      resource_type: 'skill',
      resource_id: String(skill.id),
      target_scope: targetScope.value
    })
    ElMessage.success('已提交评审')
    pendingApprovalSkillIds.value.add(skill.id)
    submitDialogVisible.value = false
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '提交失败')
  } finally {
    submitting.value = false
  }
}

function getConfigStatusType(status: string): string {
  const types: Record<string, string> = {
    valid: 'success',
    not_configured: 'info',
    missing_fields: 'warning',
    invalid_format: 'danger',
    no_schema: 'info'
  }
  return types[status] || 'info'
}

function getConfigStatusText(status: string): string {
  const textKeys: Record<string, string> = {
    valid: 'skill.configuredStatus',
    not_configured: 'skill.notConfigured',
    missing_fields: 'skill.missingFields',
    invalid_format: 'skill.invalidFormat',
    no_schema: 'skill.noSchema'
  }
  return textKeys[status] ? $t(textKeys[status]) : status
}

function getConfigAlertTitle(status: string): string {
  const titleKeys: Record<string, string> = {
    not_configured: 'skill.notConfiguredYet',
    missing_fields: 'skill.incompleteConfig',
    invalid_format: 'skill.configFormatError'
  }
  return titleKeys[status] ? $t(titleKeys[status]) : ''
}

async function fetchSkills() {
  loading.value = true
  try {
    const res = await api.get('/skills')
    // 后端返回 List[SkillResponse]，直接是数组
    const list = Array.isArray(res.data) ? res.data : (res.data.skills || [])
    skills.value = list.map((s: any) => ({
      ...s,
      enabled: s.is_active !== false,
      auto_load: s.always_activate || false,
      _source: s.source || 'db',    // skill 来源：db / file
      _scope: s.scope || 'user',    // 可见范围
      isFileSkill: s.source === 'file',  // 文件技能不可编辑/删除
      metadata: {
        title: s.display_name || s.name,
        description: s.description || '',
        tags: s.tags || [],
        always: s.always_activate || false,
      },
      configStatus: 'no_schema',
      hasSchema: false,
    }))
  } catch (error: any) {
    console.error('Failed to fetch skills:', error)
  } finally {
    loading.value = false
  }
}

function showCreateDialog() {
  editingSkill.value = null
  Object.assign(form, {
    name: '',
    title: '',
    description: '',
    tags: [],
    auto_load: false,
    scope: userStore.isSuperAdmin ? 'system' : (userStore.isOrgAdmin ? 'org' : 'user'),
    content: ''
  })
  contentInputMethod.value = 'paste'
  uploadedFileName.value = ''
  dialogVisible.value = true
}

function showEditDialog(skill: Skill) {
  editingSkill.value = skill
  contentInputMethod.value = 'paste'
  Object.assign(form, {
    name: skill.name,
    title: skill.display_name || skill.metadata?.title || '',
    description: skill.description || skill.metadata?.description || '',
    tags: skill.metadata?.tags || [],
    auto_load: skill.always_activate || skill.auto_load || false,
    content: '',
    skill_format: skill.skill_format || 'markdown',
  })

  // 文件技能：直接从列表数据中取 content
  if (skill.isFileSkill && (skill as any).content) {
    form.content = (skill as any).content
    dialogVisible.value = true
  } else if (skill.id) {
    // DB 技能：异步加载 content
    api.get(`/skills/${skill.id}/content`).then(res => {
      form.content = res.data.content || ''
    }).catch(() => {
      form.content = ''
    })
    dialogVisible.value = true
  } else {
    dialogVisible.value = true
  }
}

async function showConfigDialog(skill: Skill) {
  configSkill.value = skill
  configSchema.value = null
  configForm.value = {}
  configStatus.value = null
  configDialogVisible.value = true
  // 从后端加载 schema 和配置状态
  try {
    const [schemaRes, statusRes] = await Promise.all([
      api.get(`/skills/${encodeURIComponent(skill.name)}/schema`),
      api.get(`/skills/${encodeURIComponent(skill.name)}/config`),
    ])
    configSchema.value = schemaRes.data
    if (statusRes.data) {
      configForm.value = statusRes.data.config || {}
      configStatus.value = statusRes.data
    }
  } catch {
    // schema 不存在时不报错，显示空状态让用户手动创建
  }
}

async function toggleSkill(skill: Skill) {
  try {
    await api.put(`/skills/${skill.id}`, { is_active: skill.enabled })
    ElMessage.success(skill.enabled ? $t('skill.enabled') : $t('skill.disabled'))
  } catch {
    skill.enabled = !skill.enabled
    ElMessage.error($t('skill.operationFailed'))
  }
}

async function handleSubmit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    if (editingSkill.value) {
      const skill = editingSkill.value
      if (skill.isFileSkill) {
        // 文件技能：调文件 API
        await api.put(`/skills/file/${encodeURIComponent(skill.name)}`, {
          display_name: form.title,
          description: form.description,
          content: form.content,
        })
      } else {
        // DB 技能：调 DB API
        await api.put(`/skills/${skill.id}`, {
          display_name: form.title,
          description: form.description,
          content: form.content,
          always_activate: form.auto_load,
          tags: form.tags,
          scope: form.scope,
        })
      }
      ElMessage.success($t('skill.updated'))
    } else {
      // 新建
      if (contentInputMethod.value === 'upload' && uploadedZipFile.value) {
        // ZIP 上传 → FormData
        const fd = new FormData()
        fd.append('file', uploadedZipFile.value)
        await api.post('/skills/upload-zip', fd, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
        uploadedZipFile.value = null
      } else {
        // 粘贴内容 → JSON
        await api.post('/skills', {
          name: form.name,
          display_name: form.title,
          description: form.description,
          content: form.content,
          always_activate: form.auto_load,
          tags: form.tags,
          scope: form.scope,
        })
      }
      ElMessage.success($t('skill.created'))
    }
    dialogVisible.value = false
    fetchSkills()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || $t('skill.operationFailed'))
  } finally {
    submitting.value = false
  }
}

// 处理技能压缩包上传
const uploadedZipFile = ref<File | null>(null)

async function handleSkillPackageChange(file: any) {
  if (!file.raw) return
  uploadedZipFile.value = file.raw
  uploadedFileName.value = file.raw.name

  // 从文件名推断技能名称
  if (!form.name) {
    form.name = file.raw.name.replace(/\.zip$/i, '').replace(/[^a-zA-Z0-9_\\-]/g, '-').toLowerCase()
  }
  // 预填内容占位（实际解压在后端）
  form.content = '# 从 ZIP 加载中...'

  // 清除文件列表
  if (skillUploadRef.value) {
    skillUploadRef.value.clearFiles()
  }
}

async function saveConfig() {
  if (!configSkill.value) return

  savingConfig.value = true
  try {
    await api.put(`/skills/${encodeURIComponent(configSkill.value.name)}/config`, { config: configForm.value })
    ElMessage.success($t('skill.configSaved'))
    configDialogVisible.value = false
    fetchSkills()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || $t('skill.saveFailed'))
  } finally {
    savingConfig.value = false
  }
}

async function resetConfig() {
  if (!configSkill.value || !configSchema.value) return

  configForm.value = {}
  configSchema.value.fields?.forEach((field: any) => {
    if (field.type === 'object') {
      configForm.value[field.key] = {}
    } else if (field.default !== undefined) {
      configForm.value[field.key] = field.default
    }
  })
}

async function fixConfig() {
  if (!configSkill.value) return

  try {
    await api.post(`/skills/${encodeURIComponent(configSkill.value.name)}/config/fix`)
    ElMessage.success($t('skill.configFixed'))
    showConfigDialog(configSkill.value)
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || $t('skill.fixFailed'))
  }
}

async function publishFileSkill(skill: Skill) {
  if (!skill.isFileSkill) return
  const scope = userStore.isSuperAdmin ? 'system' : 'org'
  const scopeLabel = scope === 'system' ? '系统' : '组织'
  try {
    await ElMessageBox.confirm(
      `将文件技能 "${skill.name}" 发布为${scopeLabel}级技能？发布后所有用户可见。`,
      '发布技能',
      { type: 'info' }
    )
    await api.post(`/skills/file/${encodeURIComponent(skill.name)}/promote`, { scope })
    ElMessage.success('发布成功')
    fetchSkills()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e.response?.data?.detail || '发布失败')
    }
  }
}

async function deleteSkill(skill: Skill) {
  try {
    await ElMessageBox.confirm($t('skill.confirmDeleteSkill', { name: skill.name }), $t('skill.confirmDelete'), { type: 'warning' })
    if (skill.isFileSkill) {
      await api.delete(`/skills/file/${encodeURIComponent(skill.name)}`)
    } else {
      await api.delete(`/skills/${skill.id}`)
    }
    ElMessage.success($t('skill.deleted'))
    fetchSkills()
  } catch {}
}

async function reloadSkills() {
  reloading.value = true
  try {
    const res = await api.post('/skills/reload')
    ElMessage.success(res.data.message || $t('skill.skillsReloaded'))
    fetchSkills()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || $t('skill.reloadFailed'))
  } finally {
    reloading.value = false
  }
}

async function checkDependencies(skill: any) {
  try {
    const res = await api.get(`/skills/${skill.id}/check-dependencies`)
    const data = res.data
    if (data.satisfied) {
      ElMessage.success($t('skill.allDependenciesSatisfied'))
    } else {
      const missingList = data.missing.map((m: any) => m.message).join('\n')
      ElMessageBox.alert(missingList, $t('skill.missingDependencies'), { type: 'warning' })
    }
  } catch (error: any) {
    ElMessage.error($t('skill.checkFailed'))
  }
}

async function createSchema() {
  try {
    const fields = JSON.parse(schemaForm.fieldsJson)
    await api.post(`/skills/${encodeURIComponent(schemaForm.skill_name)}/schema`, {
      skill_name: schemaForm.skill_name,
      version: schemaForm.version,
      description: schemaForm.description,
      fields
    })
    ElMessage.success($t('skill.schemaCreated'))
    showSchemaDialog.value = false
    fetchSkills()
  } catch (error: any) {
    ElMessage.error($t('skill.createFailed') + ': ' + (error.response?.data?.detail || error.message))
  }
}

function copyTemplate(code: string) {
  navigator.clipboard.writeText(code)
  ElMessage.success($t('skill.copiedToClipboard'))
}

async function loadPendingApprovals() {
  try {
    const res = await api.get('/approvals', { params: { status_filter: 'pending' } })
    const approvals = Array.isArray(res.data) ? res.data : (res.data.items || [])
    for (const a of approvals) {
      if (a.resource_type === 'skill' && a.requester_id === userStore.user?.id) {
        pendingApprovalSkillIds.value.add(Number(a.resource_id))
      }
    }
  } catch { /* ignore */ }
}

onMounted(() => {
  fetchSkills()
  loadPendingApprovals()
})
</script>

<style scoped lang="scss">
.skills-page {
  padding: 0;
}

// ── Stat Cards ──
.skill-stats {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 24px;

    .stat-card {
      background: var(--pc-glass-bg);
      border: 1px solid var(--pc-glass-border);
      border-radius: var(--pc-radius-lg);
      backdrop-filter: var(--pc-glass-blur);
      transition: all 0.25s ease;

      &:hover {
        border-color: rgba(var(--pc-primary-rgb), 0.3);
        box-shadow: 0 0 20px rgba(var(--pc-primary-rgb), 0.1);
      }

      :deep(.el-card__body) {
        display: flex;
        align-items: center;
        gap: 16px;
        padding: 18px;
        background: transparent;
      }

      .stat-icon {
        width: 48px;
        height: 48px;
        border-radius: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #fff;
        font-size: 22px;

        &.total {
          background: var(--pc-primary);
          box-shadow: 0 0 14px rgba(var(--pc-primary-rgb), 0.35);
        }
        &.active {
          background: var(--pc-accent-green);
          box-shadow: 0 0 14px rgba(var(--pc-accent-green), 0.3);
        }
        &.configured {
          background: var(--pc-accent-purple);
          box-shadow: 0 0 14px rgba(var(--pc-accent-purple), 0.3);
        }
        &.system {
          background: var(--pc-accent-orange);
          box-shadow: 0 0 14px rgba(var(--pc-accent-orange), 0.3);
        }
      }

      .stat-info {
        .stat-value {
          font-size: 26px;
          font-weight: 700;
          color: var(--pc-text-primary);
          letter-spacing: 0.5px;
        }
        .stat-label {
          font-size: 12px;
          color: var(--pc-text-muted);
          text-transform: uppercase;
          letter-spacing: 1px;
          margin-top: 2px;
        }
      }
    }
  }

  // ── Skills Table Card ──
  .skills-card {
    background: var(--pc-glass-bg) !important;
    border: 1px solid var(--pc-glass-border) !important;
    border-radius: var(--pc-radius-lg) !important;
    backdrop-filter: var(--pc-glass-blur);

    :deep(.el-card__body) {
      background: transparent;
    }

    .skill-name-cell {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;

      .skill-name {
        font-weight: 600;
        color: var(--pc-text-primary);
      }
    }
  }

  // ── Config Form ──
  .config-form {
    .object-fields {
      padding-left: 20px;
      border-left: 2px solid var(--pc-primary);
      margin-left: 10px;
    }

    .field-desc {
      font-size: 12px;
      color: var(--pc-text-muted);
      margin-top: 4px;
    }
  }

  // ── Form Hint ──
  .form-hint {
    margin-left: 12px;
    font-size: 12px;
    color: var(--pc-text-muted);
  }

  // ── Muted small text ──
  .text-muted-sm {
    color: var(--pc-text-muted);
    font-size: 12px;
  }

  // ── Monospace input ──
  .monospace-input :deep(textarea),
  .monospace-input :deep(input) {
    font-family: 'JetBrains Mono', 'Fira Code', 'Monaco', 'Menlo', monospace !important;
  }

  // ── Schema Templates ──
  .schema-templates {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 16px;

    .template-card {
      background: var(--pc-glass-bg) !important;
      border: 1px solid var(--pc-glass-border) !important;
      border-radius: var(--pc-radius-lg);
      transition: all 0.25s ease;

      &:hover {
        border-color: rgba(var(--pc-primary-rgb), 0.3);
        box-shadow: 0 0 16px rgba(var(--pc-primary-rgb), 0.1);
      }

      :deep(.el-card__body) {
        background: transparent;
      }

      .template-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;

        .template-name {
          font-weight: 600;
          color: var(--pc-text-primary);
        }
      }

      .template-code {
        background: var(--pc-bg-deep);
        color: var(--pc-text-primary);
        padding: 14px;
        border-radius: 8px;
        font-size: 12px;
        font-family: 'JetBrains Mono', 'Fira Code', 'Monaco', 'Menlo', monospace;
        overflow-x: auto;
        margin-bottom: 12px;
        border: 1px solid var(--pc-border);
      }
    }
  }

  // ── Cyberpunk Buttons ──
  .cyber-btn {
    &.ghost {
      border: 1px solid var(--pc-border);
      color: var(--pc-text-secondary);
      background: transparent;
      transition: all 0.2s;

      &:hover {
        border-color: var(--pc-primary);
        color: var(--pc-primary);
        box-shadow: 0 0 10px rgba(var(--pc-primary-rgb), 0.15);
      }
    }

    &.primary-glow {
      box-shadow: 0 0 14px rgba(var(--pc-primary-rgb), 0.3);
      transition: box-shadow 0.25s;

      &:hover {
        box-shadow: 0 0 22px rgba(var(--pc-primary-rgb), 0.5);
      }
    }
  }

  // ── Cyberpunk Dialog ──
  :deep(.cyber-dialog) {
    .el-dialog {
      background: var(--pc-glass-bg) !important;
      border: 1px solid var(--pc-glass-border) !important;
      border-radius: var(--pc-radius-lg) !important;
      backdrop-filter: var(--pc-glass-blur);
      box-shadow: var(--pc-shadow-lg), var(--pc-shadow-glow);

      .el-dialog__header {
        border-bottom: 1px solid var(--pc-border);
        padding: 16px 20px;

        .el-dialog__title {
          color: var(--pc-text-primary) !important;
          font-weight: 600;
          letter-spacing: 0.5px;
        }
      }

      .el-dialog__body {
        color: var(--pc-text-secondary);
      }

      .el-dialog__footer {
        border-top: 1px solid var(--pc-border);
        padding: 12px 20px;
      }
    }
  }

  // ── Submit Review Dialog ──
  .submit-review-body {
    .submit-intro {
      color: var(--pc-text-secondary);
      margin-bottom: 20px;
      line-height: 1.8;

      .skill-highlight {
        color: var(--pc-text-primary);
        font-weight: 600;
      }
    }

    .scope-cards {
      display: flex;
      gap: 16px;
    }

    .scope-card {
      flex: 1;
      position: relative;
      display: flex;
      align-items: flex-start;
      gap: 16px;
      padding: 20px;
      border-radius: var(--pc-radius-lg);
      border: 2px solid var(--pc-border);
      background: var(--pc-bg-surface);
      cursor: pointer;
      transition: all 0.25s ease;

      &:hover {
        border-color: rgba(var(--pc-primary-rgb), 0.3);
        background: rgba(var(--pc-primary-rgb), 0.02);
      }

      &.selected {
        border-color: var(--pc-primary);
        background: rgba(var(--pc-primary-rgb), 0.06);
        box-shadow: 0 0 20px rgba(var(--pc-primary-rgb), 0.15);
      }

      .scope-card-icon {
        width: 48px;
        height: 48px;
        border-radius: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;

        &.org-icon {
          background: rgba(var(--pc-accent-orange-rgb), 0.12);
          color: var(--pc-accent-orange);
        }

        &.sys-icon {
          background: rgba(var(--pc-accent-red-rgb), 0.12);
          color: var(--pc-accent-red);
        }
      }

      .scope-card-body {
        flex: 1;
        min-width: 0;

        .scope-card-title {
          margin-bottom: 6px;
        }

        .scope-card-desc {
          color: var(--pc-text-muted);
          font-size: 13px;
          line-height: 1.5;
          margin: 0;
        }
      }

      .scope-card-check {
        position: absolute;
        top: 12px;
        right: 12px;
        width: 24px;
        height: 24px;
        border-radius: 50%;
        background: var(--pc-primary);
        color: #fff;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 14px;
        box-shadow: 0 0 10px rgba(var(--pc-primary-rgb), 0.4);
      }
    }
  }

  // Ensure submit-review dialog has proper glass styling
  :deep(.submit-review-dialog) {
    .el-dialog {
      background: var(--pc-glass-bg) !important;
      border: 1px solid var(--pc-glass-border) !important;
      border-radius: var(--pc-radius-lg) !important;
      backdrop-filter: var(--pc-glass-blur);
      box-shadow: var(--pc-shadow-lg), var(--pc-shadow-glow);

      .el-dialog__header {
        border-bottom: 1px solid var(--pc-border);
        padding: 16px 20px;

        .el-dialog__title {
          color: var(--pc-text-primary) !important;
          font-weight: 600;
        }
      }

      .el-dialog__body {
        color: var(--pc-text-secondary);
      }

      .el-dialog__footer {
        border-top: 1px solid var(--pc-border);
        padding: 12px 20px;
      }
    }
  }

  // ── Cyberpunk Table overrides ──
  :deep(.cyber-table) {
    --el-table-bg-color: transparent;
    --el-table-tr-bg-color: transparent;
    --el-table-header-bg-color: var(--pc-bg-surface);
    --el-table-row-hover-bg-color: rgba(var(--pc-primary-rgb), 0.04);
    --el-table-border-color: var(--pc-border);
    --el-table-text-color: var(--pc-text-primary);
    --el-table-header-text-color: var(--pc-text-secondary);

    th.el-table__cell {
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      font-size: 11px;
    }
  }

  // 操作栏按钮窄一点
  .pc-action-group .el-button--small {
    padding-left: 8px;
    padding-right: 8px;
  }
</style>
