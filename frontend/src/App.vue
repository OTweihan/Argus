<template>
  <div class="shell">
    <aside class="sidebar">
      <h1 class="brand">Argus</h1>
      <nav class="nav">
        <button :class="{ active: view === 'dashboard' }" @click="changeView('dashboard')">
          仪表盘
        </button>
        <button :class="{ active: view === 'projects' }" @click="changeView('projects')">
          项目
        </button>
        <button :class="{ active: view === 'tasks' }" @click="changeView('tasks')">任务</button>
        <button :class="{ active: view === 'models' }" @click="changeView('models')">模型</button>
      </nav>
    </aside>

    <main class="main">
      <div class="topbar">
        <h1>{{ viewTitle }}</h1>
        <div class="status">
          <span class="dot" :class="eventStatus"></span>
          <span>事件流：{{ eventStatusText }}</span>
          <button type="button" @click="loadAll">刷新</button>
        </div>
      </div>

      <div v-if="loading" class="banner">正在加载数据。</div>
      <div v-if="message" class="banner">{{ message }}</div>
      <div v-if="error" class="banner error">{{ error }}</div>

      <template v-if="view === 'dashboard'">
        <section class="grid metrics">
          <div class="metric"><strong>{{ projects.length }}</strong><span>项目</span></div>
          <div class="metric"><strong>{{ allTasks.length }}</strong><span>任务</span></div>
          <div class="metric"><strong>{{ runningCount }}</strong><span>运行中</span></div>
          <div class="metric"><strong>{{ findingCount }}</strong><span>问题</span></div>
        </section>
        <section class="panel with-margin">
          <h2>最近任务</h2>
          <TaskTable
            :tasks="recentTasks"
            :projects="projects"
            @select="selectTask"
            @start="startTask"
          />
        </section>
      </template>

      <template v-else-if="view === 'projects'">
        <section class="grid two">
          <div class="panel">
            <h2>项目配置</h2>
            <form class="form-grid" @submit.prevent="saveProject">
              <div class="field">
                <label>名称</label>
                <input v-model="projectForm.name" required />
              </div>
              <div class="field">
                <label>描述</label>
                <textarea v-model="projectForm.description"></textarea>
              </div>
              <div class="field">
                <label>基础 URL</label>
                <input v-model="projectForm.baseUrl" placeholder="https://example.com" />
              </div>
              <div class="field">
                <label>Git URL</label>
                <input v-model="projectForm.gitUrl" />
              </div>
              <div class="field">
                <label>登录态名称</label>
                <input v-model="projectForm.authStateName" />
              </div>
              <div class="form-grid two">
                <div class="field">
                  <label>默认最大步骤</label>
                  <input v-model="projectForm.defaultMaxSteps" type="number" min="1" />
                </div>
                <div class="field">
                  <label>默认超时秒数</label>
                  <input v-model="projectForm.defaultTimeoutSeconds" type="number" min="1" />
                </div>
              </div>
              <div class="checks">
                <label>
                  <input v-model="projectForm.defaultCaptureScreenshots" type="checkbox" />
                  截图
                </label>
              </div>
              <div class="field">
                <label>参数 JSON</label>
                <textarea v-model="projectForm.parameters"></textarea>
              </div>
              <div class="actions">
                <button class="primary" type="submit">保存项目</button>
                <button type="button" @click="resetProjectForm">清空</button>
              </div>
            </form>
          </div>
          <div class="panel">
            <h2>项目列表</h2>
            <ProjectTable :projects="projects" @edit="editProject" @delete="deleteProject" />
          </div>
        </section>
      </template>

      <template v-else-if="view === 'tasks'">
        <section class="grid two">
          <div class="panel">
            <h2>创建任务</h2>
            <form class="form-grid" @submit.prevent="saveTask">
              <div class="field">
                <label>项目</label>
                <select v-model="taskForm.projectId" required>
                  <option
                    v-for="project in projects"
                    :key="project.projectId"
                    :value="project.projectId"
                  >
                    {{ project.name }}
                  </option>
                </select>
              </div>
              <div class="field">
                <label>目标</label>
                <textarea v-model="taskForm.goal" required></textarea>
              </div>
              <div class="field">
                <label>起始 URL</label>
                <input v-model="taskForm.startUrl" />
              </div>
              <div class="form-grid two">
                <div class="field">
                  <label>最大步骤</label>
                  <input v-model="taskForm.maxSteps" type="number" min="1" />
                </div>
                <div class="field">
                  <label>超时秒数</label>
                  <input v-model="taskForm.timeoutSeconds" type="number" min="1" />
                </div>
              </div>
              <div class="field">
                <label>模型配置</label>
                <select v-model="taskForm.modelConfigId">
                  <option value="">默认模型</option>
                  <option
                    v-for="model in enabledModels"
                    :key="model.modelConfigId"
                    :value="model.modelConfigId"
                  >
                    {{ model.name }}
                  </option>
                </select>
              </div>
              <div class="field">
                <label>截图</label>
                <select v-model="taskForm.captureScreenshots">
                  <option value="">使用项目默认</option>
                  <option value="true">开启</option>
                  <option value="false">关闭</option>
                </select>
              </div>
              <div class="field">
                <label>参数 JSON</label>
                <textarea v-model="taskForm.parameters"></textarea>
              </div>
              <div class="actions">
                <button class="primary" type="submit">创建任务</button>
              </div>
            </form>
          </div>
          <div class="panel">
            <h2>任务列表</h2>
            <div class="actions filter-actions">
              <select v-model="taskStatusFilter">
                <option value="">全部状态</option>
                <option v-for="status in taskStatuses" :key="status" :value="status">
                  {{ status }}
                </option>
              </select>
              <select v-model="taskProjectFilter">
                <option value="">全部项目</option>
                <option
                  v-for="project in projects"
                  :key="project.projectId"
                  :value="project.projectId"
                >
                  {{ project.name }}
                </option>
              </select>
            </div>
            <TaskTable
              :tasks="visibleTasks"
              :projects="projects"
              @select="selectTask"
              @start="startTask"
            />
          </div>
        </section>
        <section class="panel with-margin">
          <h2>任务详情</h2>
          <TaskDetail v-if="selectedTask" :task="selectedTask" />
          <div v-else class="empty">暂无任务。</div>
        </section>
      </template>

      <template v-else>
        <section class="grid two">
          <div class="panel">
            <h2>模型配置</h2>
            <form class="form-grid" @submit.prevent="saveModel">
              <div class="field">
                <label>名称</label>
                <input v-model="modelForm.name" required />
              </div>
              <div class="form-grid two">
                <div class="field">
                  <label>供应商</label>
                  <select v-model="modelForm.provider">
                    <option v-for="provider in providers" :key="provider" :value="provider">
                      {{ provider }}
                    </option>
                  </select>
                </div>
                <div class="field">
                  <label>模型</label>
                  <input v-model="modelForm.model" required />
                </div>
              </div>
              <div class="field">
                <label>API Key</label>
                <input v-model="modelForm.apiKey" type="password" autocomplete="new-password" />
              </div>
              <div class="field">
                <label>Base URL</label>
                <input v-model="modelForm.baseUrl" />
              </div>
              <div class="field">
                <label>Completions Path</label>
                <input v-model="modelForm.completionsPath" />
              </div>
              <div class="form-grid two">
                <div class="field">
                  <label>最大 Token</label>
                  <input v-model="modelForm.maxTokens" type="number" min="1" />
                </div>
                <div class="field">
                  <label>温度</label>
                  <input v-model="modelForm.temperature" type="number" min="0" step="0.01" />
                </div>
              </div>
              <div class="form-grid two">
                <div class="field">
                  <label>重试次数</label>
                  <input v-model="modelForm.maxRetries" type="number" min="0" />
                </div>
                <div class="field">
                  <label>超时秒数</label>
                  <input v-model="modelForm.timeoutSeconds" type="number" min="1" />
                </div>
              </div>
              <div class="field">
                <label>任务类型默认</label>
                <select v-model="modelForm.taskType">
                  <option value="">全局默认</option>
                  <option value="blackbox">blackbox</option>
                  <option value="whitebox">whitebox</option>
                </select>
              </div>
              <div class="checks">
                <label><input v-model="modelForm.isDefault" type="checkbox" /> 默认</label>
                <label><input v-model="modelForm.enabled" type="checkbox" /> 启用</label>
              </div>
              <div class="actions">
                <button class="primary" type="submit">保存模型</button>
                <button type="button" @click="testModel('')">测试</button>
                <button type="button" @click="resetModelForm">清空</button>
              </div>
            </form>
          </div>
          <div class="panel">
            <h2>模型列表</h2>
            <ModelTable
              :models="models"
              @edit="editModel"
              @test="testModel"
              @delete="deleteModel"
            />
          </div>
        </section>
      </template>
    </main>

    <div v-if="dialog" class="dialog-backdrop" @click.self="closeDialog">
      <div class="dialog" :class="dialog.tone" role="dialog" aria-modal="true">
        <div class="dialog-header">
          <h2>{{ dialog.title }}</h2>
          <button type="button" aria-label="关闭" @click="closeDialog">×</button>
        </div>
        <div class="dialog-body">{{ dialog.message }}</div>
        <div class="dialog-actions">
          <button class="primary" type="button" @click="closeDialog">确定</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import ModelTable from "./components/ModelTable.vue";
import ProjectTable from "./components/ProjectTable.vue";
import TaskDetail from "./components/TaskDetail.vue";
import TaskTable from "./components/TaskTable.vue";
import { useConsoleApp } from "./composables/useConsoleApp";

const {
  allTasks,
  changeView,
  closeDialog,
  deleteModel,
  deleteProject,
  dialog,
  editModel,
  editProject,
  enabledModels,
  error,
  eventStatus,
  eventStatusText,
  findingCount,
  loadAll,
  loading,
  message,
  modelForm,
  models,
  projectForm,
  projects,
  providers,
  recentTasks,
  resetModelForm,
  resetProjectForm,
  runningCount,
  saveModel,
  saveProject,
  saveTask,
  selectTask,
  selectedTask,
  startTask,
  taskForm,
  taskProjectFilter,
  taskStatuses,
  taskStatusFilter,
  testModel,
  view,
  viewTitle,
  visibleTasks,
} = useConsoleApp();
</script>
