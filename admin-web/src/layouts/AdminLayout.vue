<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import { language, setLanguage, tr, type Language } from "../i18n";
import spiderMark from "../assets/spider-mark.svg";
import webUrlIcon from "../assets/web-url.svg";

const route = useRoute();
const activeMenu = computed(() => {
  const section = route.path.split("/")[1];
  if (route.path !== "/" && ["software", "artifacts", "jobs"].includes(section))
    return `/${section}`;
  return route.path;
});
const currentSection = computed(() => {
  const path = route.path.split("/")[1];
  const sections: Record<string, [string, string]> = {
    candidates: ["软件候选池", "Candidates"],
    software: ["已抓取软件", "Crawled software"],
    releases: ["软件版本", "Releases"],
    variants: ["运行环境", "Variants"],
    artifacts: ["安装包文件", "Artifacts"],
    sources: ["抓取池来源", "Sources"],
    links: ["网盘链接与下载入口", "Download links"],
    downloads: ["下载任务", "Downloads"],
    storage: ["文件存储位置", "Storage"],
    content: ["生成内容草稿", "Content drafts"],
    publishing: ["电商发布文案", "Publishing"],
    jobs: ["后台任务", "Jobs"],
    settings: ["系统设置", "Settings"],
  };
  const label = sections[path];
  return label ? tr(label[0], label[1]) : tr("管理概览", "Overview");
});

function changeLanguage(value: string | number | boolean | undefined): void {
  if (value === "zh-CN" || value === "en-US") setLanguage(value as Language);
}
</script>

<template>
  <el-container class="shell">
    <el-aside width="232px"
              class="sidebar">
      <router-link to="/"
                   class="brand"
                   :aria-label="tr('返回管理概览', 'Back to overview')">
        <img class="brand-mark" :src="spiderMark" alt="" aria-hidden="true" />
        <span class="brand-copy"><strong>software<span>_</span>spider</strong><small>RESOURCE STUDIO / ADMIN</small></span>
      </router-link>
      <div class="sidebar-caption">{{ tr('工作空间', 'WORKSPACE') }}</div>
      <el-menu router
               :default-active="activeMenu"
               class="nav">
        <el-menu-item index="/"><span class="nav-symbol">⌂</span>{{ tr('管理概览', 'Overview') }}</el-menu-item>
        <el-sub-menu index="discovery"><template #title><span class="nav-symbol">◇</span>{{ tr('软件发现', 'Discovery') }}</template>
          <el-menu-item index="/candidates">{{ tr('软件候选池', 'Candidates') }}</el-menu-item>
          <el-menu-item index="/crawl-pools"><img class="menu-icon" :src="webUrlIcon" alt="" aria-hidden="true" />{{ tr('URL 抓取池', 'URL crawl pool') }}</el-menu-item>
          <el-menu-item index="/links">{{ tr('网盘链接与下载入口', 'Download links') }}</el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="catalog"><template #title><span class="nav-symbol">▦</span>{{ tr('资源目录', 'Catalog') }}</template>
          <el-menu-item index="/software">{{ tr('已抓取软件', 'Crawled software') }}</el-menu-item>
          <el-menu-item index="/sources">{{ tr('已收录软件来源', 'Catalog software sources') }}</el-menu-item>
          <el-menu-item index="/releases">{{ tr('软件版本', 'Releases') }}</el-menu-item>
          <el-menu-item index="/variants">{{ tr('版本运行环境', 'Variants') }}</el-menu-item>
          <el-menu-item index="/artifacts">{{ tr('安装包文件', 'Artifacts') }}</el-menu-item>
        </el-sub-menu>
        <el-menu-item index="/downloads"><span class="nav-symbol">↓</span>{{ tr('下载任务', 'Downloads') }}</el-menu-item>
        <el-menu-item index="/storage"><span class="nav-symbol">▤</span>{{ tr('文件存储位置', 'Storage') }}</el-menu-item>
        <el-menu-item index="/content"><span class="nav-symbol">✎</span>{{ tr('生成内容草稿', 'Content drafts') }}</el-menu-item>
        <el-menu-item index="/publishing"><span class="nav-symbol">↗</span>{{ tr('电商发布文案', 'Publishing') }}</el-menu-item>
        <el-menu-item index="/jobs"><span class="nav-symbol">◷</span>{{ tr('后台任务', 'Jobs') }}</el-menu-item>
      </el-menu>
      <div class="sidebar-foot">
        <router-link to="/settings"
                     class="sidebar-settings"><span class="nav-symbol">⚙</span>{{ tr('系统设置', 'Settings') }}</router-link>
        <span class="sidebar-edition">SOFTWARE RESOURCE MANAGEMENT</span>
      </div>
    </el-aside>
    <el-container class="main-shell">
      <el-header class="header">
        <div class="header-location"><span class="header-eyebrow">SOFTWARE SPIDER / ADMIN</span><strong>{{ currentSection }}</strong></div>
        <div class="header-actions"><span class="local-indicator"><i></i>{{ tr('本地工作台', 'Local workspace') }}</span>
          <el-select :model-value="language"
                     size="small"
                     class="language-select"
                     :aria-label="tr('切换语言', 'Switch language')"
                     @change="changeLanguage">
            <el-option label="简体中文"
                       value="zh-CN" /><el-option label="English"
                       value="en-US" />
          </el-select>
        </div>
      </el-header>
      <el-main>
        <div class="content-frame"><router-view /></div>
      </el-main>
    </el-container>
  </el-container>
</template>
