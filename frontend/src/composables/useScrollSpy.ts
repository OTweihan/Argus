import { onMounted, onUnmounted, ref } from "vue";

export function useScrollSpy(
    sectionSelector = "[data-section]",
    rootMargin = "-80px 0px -60% 0px",
) {
    const activeSection = ref("");
    let observer: IntersectionObserver | null = null;

    onMounted(() => {
        const sections = document.querySelectorAll(sectionSelector);
        if (!sections.length) return;
        observer = new IntersectionObserver(
            (entries) => {
                for (const entry of entries) {
                    if (entry.isIntersecting) {
                        activeSection.value = entry.target.id;
                    }
                }
            },
            { rootMargin },
        );
        sections.forEach((s) => observer!.observe(s));
        activeSection.value = sections[0].id;
    });

    onUnmounted(() => {
        observer?.disconnect();
    });

    return { activeSection };
}
