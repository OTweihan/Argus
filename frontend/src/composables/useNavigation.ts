import { onMounted, onUnmounted, ref } from "vue";

export type ViewKey = "dashboard" | "projects" | "tasks" | "models" | "task-detail";

export function useNavigation() {
    const view = ref<ViewKey>("dashboard");

    function changeView(nextView: ViewKey): void {
        view.value = nextView;
        window.location.hash = nextView;
    }

    function onHashChange(): void {
        const hash = window.location.hash.replace(/^#/, "");
        if ((["dashboard", "projects", "tasks", "models", "task-detail"] as ViewKey[]).includes(hash as ViewKey)) {
            view.value = hash as ViewKey;
        }
    }

    onMounted(() => {
        const hash = window.location.hash.replace(/^#/, "");
        if ((["dashboard", "projects", "tasks", "models", "task-detail"] as ViewKey[]).includes(hash as ViewKey)) {
            view.value = hash as ViewKey;
        }
        window.addEventListener("hashchange", onHashChange);
    });

    onUnmounted(() => {
        window.removeEventListener("hashchange", onHashChange);
    });

    return { view, changeView };
}
