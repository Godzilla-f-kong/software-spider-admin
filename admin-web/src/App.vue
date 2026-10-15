<script setup lang="ts">
import { computed } from 'vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import en from 'element-plus/es/locale/lang/en'
import { language } from './i18n'

const elementLocale = computed(() => language.value === 'zh-CN' ? zhCn : en)
</script>
<template><el-config-provider :locale="elementLocale"><router-view /></el-config-provider></template>
