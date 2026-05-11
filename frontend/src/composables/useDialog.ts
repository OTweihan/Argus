import { computed, nextTick, ref } from "vue";

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

    function showDialog(title: string, message: string, tone: DialogTone): void {
        dialog.value = { title, message, tone };
        void nextTick(() => {
            document.querySelector<HTMLButtonElement>(".dialog-actions button")?.focus();
        });
    }

    function closeDialog(): void {
        dialog.value = null;
    }

    return { dialog, dialogVisible, showDialog, closeDialog };
}
