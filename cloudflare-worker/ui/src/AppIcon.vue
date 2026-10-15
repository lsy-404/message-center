<script setup lang="ts">
import { computed } from 'vue'
import { icons, type IconName } from './icons'

const props = withDefaults(defineProps<{ name: IconName, size?: number }>(), { size: 16 })
const icon = computed(() => icons[props.name])
</script>

<template>
  <svg
    class="app-icon"
    :width="size"
    :height="size"
    :viewBox="`0 0 ${icon[0]} ${icon[0]}`"
    aria-hidden="true"
    focusable="false"
  ><path :d="icon[1]" fill="currentColor" /></svg>
</template>
