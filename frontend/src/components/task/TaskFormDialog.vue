<template>
  <el-dialog
    :model-value="visible" :title="editing ? '编辑任务' : '创建任务'"
    width="800px" align-center append-to-body @update:model-value="$emit('close')"
  >
    <el-form :model="localForm" label-position="top" @submit.prevent="$emit('save')">
      <!-- 任务类型 -->
      <el-form-item label="任务类型" required>
        <el-radio-group
          v-model="localForm.taskType"
          :disabled="editing"
        >
          <el-radio-button value="blackbox">
            黑盒测试
          </el-radio-button>
          <el-radio-button value="whitebox">
            白盒分析
          </el-radio-button>
        </el-radio-group>
        <div v-if="editing" class="form-hint">
          编辑已有任务时不可切换任务类型
        </div>
      </el-form-item>

      <!-- 公共字段 -->
      <el-form-item label="项目" required>
        <el-select v-model="localForm.projectId" style="width:100%">
          <el-option
            v-for="project in projects" :key="project.projectId" :label="project.name"
            :value="project.projectId"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="任务名称">
        <el-input v-model="localForm.name" maxlength="50" show-word-limit />
      </el-form-item>
      <el-form-item label="目标" :error="formErrors.goal" required>
        <el-input
          v-model="localForm.goal" type="textarea" :rows="4" maxlength="200" show-word-limit
          @input="clearError('goal')"
        />
      </el-form-item>

      <!-- ══════════ 黑盒专属字段 ══════════ -->
      <template v-if="localForm.taskType === 'blackbox'">
        <el-form-item label="起始 URL" :error="formErrors.startUrl" required>
          <el-input
            v-model="localForm.blackbox.startUrl" placeholder="https://example.com"
            @input="clearError('startUrl')"
          />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="最大步骤">
              <el-input-number
                v-model="localForm.blackbox.maxSteps" :min="1" :step="1" :precision="0"
                style="width:100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="超时秒数">
              <el-input-number
                v-model="localForm.blackbox.timeoutSeconds" :min="1" :step="1" :precision="0"
                style="width:100%"
              />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="截图">
          <el-select v-model="localForm.blackbox.captureScreenshots" style="width:100%">
            <el-option label="使用项目默认" :value="SENTINEL_DEFAULT" />
            <el-option label="开启" value="true" />
            <el-option label="关闭" value="false" />
          </el-select>
        </el-form-item>
        <el-form-item label="模型配置">
          <el-select v-model="localForm.modelConfigId" style="width:100%">
            <el-option label="默认模型" :value="SENTINEL_DEFAULT" />
            <el-option
              v-for="model in enabledModels" :key="model.modelConfigId" :label="model.name"
              :value="model.modelConfigId"
            />
          </el-select>
        </el-form-item>
        <el-collapse v-model="promptCollapseActive" class="prompt-collapse">
          <el-collapse-item name="prompt">
            <template #title>
              <span class="prompt-collapse-title">Prompt 业务扩展</span>
              <el-tag v-if="hasExt" size="small" type="success" effect="plain" class="prompt-collapse-tag">
                已配置
              </el-tag>
              <el-tag v-else size="small" type="info" effect="plain" class="prompt-collapse-tag">
                未配置
              </el-tag>
            </template>
            <PromptExtensionEditor
              v-if="promptCollapseActive.includes('prompt')"
              v-model="localForm.blackbox.promptExtensions"
              scope="task"
              :project-extensions="resolvedProjectExtensions"
            />
          </el-collapse-item>
        </el-collapse>
        <el-form-item label="参数" :error="formErrors.taskParameters">
          <div class="param-list">
            <div v-for="(entry, index) in localForm.blackbox.parameters" :key="index" class="param-row">
              <el-input
                v-model="entry.key" placeholder="键名" class="param-key"
                @input="clearError('taskParameters')"
              />
              <el-input v-model="entry.value" placeholder="值（字符串）" class="param-value" />
              <el-button type="danger" circle @click="$emit('remove-param', index)">
                ×
              </el-button>
            </div>
            <el-button class="param-add-btn" @click="$emit('add-param')">
              + 添加参数
            </el-button>
          </div>
        </el-form-item>
      </template>

      <!-- ══════════ 白盒专属字段 ══════════ -->
      <template v-if="localForm.taskType === 'whitebox'">
        <el-form-item label="模型配置">
          <el-select v-model="localForm.modelConfigId" style="width:100%">
            <el-option label="默认模型" :value="SENTINEL_DEFAULT" />
            <el-option
              v-for="model in enabledModels" :key="model.modelConfigId" :label="model.name"
              :value="model.modelConfigId"
            />
          </el-select>
        </el-form-item>

        <el-divider content-position="left">
          源码配置
        </el-divider>

        <el-form-item label="源码来源" required>
          <el-radio-group v-model="localForm.whitebox.sourceType">
            <el-radio-button value="local">
              服务端可见目录
            </el-radio-button>
            <el-radio-button value="git">
              Git 仓库
            </el-radio-button>
          </el-radio-group>
        </el-form-item>

        <template v-if="localForm.whitebox.sourceType === 'local'">
          <el-form-item label="服务端路径" :error="formErrors.sourcePath" required>
            <el-input
              v-model="localForm.whitebox.sourcePath" placeholder="/opt/workspaces/project-a"
              @input="clearError('sourcePath')"
            />
            <div class="form-hint">
              输入服务端可见的源码目录路径
            </div>
          </el-form-item>
        </template>

        <template v-if="localForm.whitebox.sourceType === 'git'">
          <el-form-item label="仓库 URL" :error="formErrors.repoUrl" required>
            <el-input
              v-model="localForm.whitebox.repoUrl"
              placeholder="https://github.com/user/repo.git"
              @input="clearError('repoUrl')"
            />
            <div class="form-hint">
              凭据由部署环境管理，请勿写入 URL
            </div>
          </el-form-item>
          <el-form-item label="分支 / Tag / Commit">
            <el-input v-model="localForm.whitebox.ref" placeholder="main（可选）" />
          </el-form-item>
        </template>

        <el-form-item label="分析范围" required>
          <el-select v-model="localForm.whitebox.scope" style="width:100%">
            <el-option label="全量分析" value="ALL" />
            <el-option label="指定模块" value="MODULES" />
          </el-select>
        </el-form-item>

        <el-form-item
          v-if="localForm.whitebox.scope === 'MODULES'"
          label="目标模块" :error="formErrors.targetModules" required
        >
          <el-input
            v-model="targetModulesText"
            placeholder="module-a, module-b"
            @input="clearError('targetModules')"
          />
          <div class="form-hint">
            多个模块用英文逗号分隔
          </div>
        </el-form-item>

        <el-divider content-position="left">
          Maven 配置
          <el-tag v-if="!mavenExpanded" size="small" type="info" effect="plain" style="margin-left:8px">
            已折叠
          </el-tag>
        </el-divider>

        <el-form-item label="Classpath 模式">
          <el-select v-model="localForm.whitebox.mavenClasspathMode" style="width:100%">
            <el-option label="自动检测" value="AUTO" />
            <el-option label="仅缓存" value="CACHE_ONLY" />
            <el-option label="Maven 构建" value="MAVEN" />
            <el-option label="仅源码" value="SOURCE_ONLY" />
          </el-select>
        </el-form-item>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="自动检测 Maven">
              <el-switch v-model="localForm.whitebox.mavenAutoDetect" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="离线模式">
              <el-switch v-model="localForm.whitebox.mavenOffline" />
            </el-form-item>
          </el-col>
        </el-row>

        <!-- Maven 高级配置 -->
        <el-collapse v-model="mavenExpanded" class="prompt-collapse">
          <el-collapse-item name="maven-advanced">
            <template #title>
              <span class="prompt-collapse-title">高级 Maven 配置</span>
            </template>

            <el-form-item label="生成 Classpath">
              <el-switch v-model="localForm.whitebox.mavenGenerateClasspath" />
            </el-form-item>

            <el-form-item label="Maven 可执行文件（服务端路径）">
              <el-input v-model="localForm.whitebox.mavenExecutable" placeholder="mvn（使用系统 PATH）" />
            </el-form-item>

            <el-form-item label="settings.xml（服务端路径）">
              <el-input v-model="localForm.whitebox.mavenSettingsXml" placeholder="~/.m2/settings.xml" />
            </el-form-item>

            <el-form-item label="本地仓库（服务端路径）">
              <el-input v-model="localForm.whitebox.mavenLocalRepository" placeholder="~/.m2/repository" />
            </el-form-item>

            <el-form-item label="Classpath 文件（服务端路径）">
              <el-input v-model="localForm.whitebox.mavenClasspathFile" />
            </el-form-item>

            <el-form-item label="准备 Reactor 产物">
              <el-switch v-model="localForm.whitebox.mavenPrepareReactorArtifacts" />
            </el-form-item>

            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="离线超时（秒）">
                  <el-input-number
                    v-model="localForm.whitebox.mavenOfflineTimeoutSeconds"
                    :min="1" :step="1" :precision="0" style="width:100%"
                  />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="在线超时（秒）">
                  <el-input-number
                    v-model="localForm.whitebox.mavenOnlineTimeoutSeconds"
                    :min="1" :step="1" :precision="0" style="width:100%"
                  />
                </el-form-item>
              </el-col>
            </el-row>
          </el-collapse-item>
        </el-collapse>
      </template>
    </el-form>
    <template #footer>
      <el-button @click="$emit('close')">
        取消
      </el-button>
      <el-button type="primary" @click="$emit('save')">
        {{ editing ? "保存" : "创建" }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, reactive, ref, watch } from "vue";
import type { ModelConfig, Project } from "../../types";
import {
  emptyPromptExtensions,
  extractPromptExtensions,
  hasAnyExtension,
  type PromptExtensions,
} from "../../promptExtensions";
import type { TaskFormState } from "../../composables/useTasks";
import { SENTINEL_DEFAULT } from "../../utils";
const PromptExtensionEditor = defineAsyncComponent(() => import("../prompt/PromptExtensionEditor.vue"));

const props = defineProps<{
  visible: boolean;
  form: TaskFormState;
  editing: boolean;
  formErrors: Record<string, string>;
  projects: Project[];
  enabledModels: ModelConfig[];
}>();

defineEmits<{
  close: [];
  save: [];
  "add-param": [];
  "remove-param": [index: number];
}>();

const promptCollapseActive = ref<string[]>([]);
const mavenExpanded = ref<string[]>([]);

const localForm = reactive<TaskFormState>({
  editingId: null,
  goal: "",
  name: "",
  projectId: "",
  modelConfigId: SENTINEL_DEFAULT,
  taskType: "blackbox",
  blackbox: {
    startUrl: "",
    maxSteps: null,
    timeoutSeconds: null,
    captureScreenshots: SENTINEL_DEFAULT,
    parameters: [],
    promptExtensions: emptyPromptExtensions(),
  },
  whitebox: {
    sourceType: "local",
    repoUrl: "",
    sourcePath: "",
    ref: "",
    scope: "ALL",
    targetModules: [],
    mavenClasspathMode: "AUTO",
    mavenOffline: false,
    mavenAutoDetect: true,
    mavenGenerateClasspath: true,
    mavenClasspathFile: "",
    mavenExecutable: "",
    mavenSettingsXml: "",
    mavenLocalRepository: "",
    mavenOfflineTimeoutSeconds: null,
    mavenOnlineTimeoutSeconds: null,
    mavenPrepareReactorArtifacts: false,
  },
});

const hasExt = computed(() => {
  if (localForm.taskType !== "blackbox") return false;
  return hasAnyExtension(localForm.blackbox.promptExtensions);
});

// targetModules 以逗号分隔的文本展示
const targetModulesText = computed({
  get: () => localForm.whitebox.targetModules.join(", "),
  set: (val: string) => {
    localForm.whitebox.targetModules = val
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  },
});

// 双向同步 props.form ↔ localForm
watch(localForm, () => {
  Object.assign(props.form, localForm);
}, { deep: true });

watch(() => props.form, (f) => {
  Object.assign(localForm, f);
}, { deep: true });

const resolvedProjectExtensions = computed<PromptExtensions>(() => {
  const project = props.projects.find((p) => p.projectId === props.form.projectId);
  if (!project) return emptyPromptExtensions();
  return extractPromptExtensions(project.parameters);
});

function clearError(key: string): void {
  delete (props.formErrors as Record<string, string | undefined>)[key];
}
</script>

<style scoped>
.param-list {
  width: 100%;
  padding: 12px;
  border-radius: var(--radius-md);
  background: var(--surface-soft);
  border: 1px dashed var(--line-soft);
}

.param-row {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 10px;
}

.param-row:last-of-type {
  margin-bottom: 12px;
}

.param-key {
  flex: 2;
}

.param-value {
  flex: 3;
}

.param-add-btn {
  margin-top: 4px;
  width: 100%;
  border-style: dashed !important;
  color: var(--brand-600);
  border-color: var(--brand-100) !important;
  background: rgba(255, 255, 255, 0.6);
  font-weight: 540;
}

.param-add-btn:hover {
  color: #ffffff;
  background-image: var(--brand-gradient);
  border-color: transparent !important;
}

.prompt-collapse {
  margin-bottom: 18px;
  border-radius: var(--radius-md, 14px);
  overflow: hidden;
}

.prompt-collapse-title {
  font-weight: 600;
}

.prompt-collapse-tag {
  margin-left: 8px;
}

.form-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-faint, #909399);
  line-height: 1.4;
}
</style>
