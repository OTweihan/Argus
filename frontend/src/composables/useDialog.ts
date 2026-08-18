import { computed, ref } from "vue";

type DialogTone = "success" | "error" | "info";

interface DialogState {
  title: string;
  message: string;
  tone: DialogTone;
}

export function useDialog() {
  const dialog = ref<DialogState | null>(null);

  const dialogVisible = computed({
    get: () => dialog.value !== null,
    set: (val: boolean) => {
      if (!val) dialog.value = null;
    },
  });

  function closeDialog(): void {
    dialog.value = null;
  }

  return { dialog, dialogVisible, closeDialog };
}
