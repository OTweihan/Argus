package com.argus.analyzer.env;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;

import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * Maven 多模块递归扫描器。
 *
 * <p>从根 POM 开始，递归解析 {@code <modules>} 标签，
 * 构建完整的模块索引。
 */
@Component
public class MavenModuleScanner {

    private static final Logger log = LoggerFactory.getLogger(MavenModuleScanner.class);

    /**
     * 从根 POM 开始递归扫描所有模块。
     *
     * @param rootPom 根 POM 路径
     * @return 模块索引
     */
    public MavenModuleIndex scan(Path rootPom) {
        Path basedir = rootPom.getParent();
        log.info("[MODULE_SCAN] Starting scan from root POM: {}", rootPom);
        List<MavenModule> modules = new ArrayList<>();
        Set<Path> visited = new HashSet<>();
        scanRecursive(rootPom, basedir, modules, visited);
        MavenModuleIndex index = new MavenModuleIndex(rootPom, basedir, modules);
        log.info("[MODULE_SCAN] Scan complete: {} modules ({} non-aggregator, {} with source roots)",
                index.getModuleCount(), index.getNonAggregatorModuleCount(),
                index.getAllSourceRoots().size());
        return index;
    }

    private void scanRecursive(Path pomFile, Path basedir, List<MavenModule> modules, Set<Path> visited) {
        Path canonical = pomFile.toAbsolutePath().normalize();
        if (!visited.add(canonical)) {
            log.debug("[MODULE_SCAN] Already visited: {}", canonical);
            return;
        }

        log.info("[MODULE_SCAN] Scanning POM: {}", canonical);
        Document doc = parseXml(canonical);
        if (doc == null) return;

        MavenModule module = parseModule(doc, canonical, basedir);
        modules.add(module);
        log.info("[MODULE_SCAN] Parsed module: {} (packaging={}, sourceRoots={})",
                module.getCoordinate(), module.getPackaging(), module.getSourceRoots().size());

        // 解析 <modules>
        NodeList moduleNodes = doc.getDocumentElement().getElementsByTagName("modules");
        if (moduleNodes.getLength() > 0) {
            Element modulesEl = (Element) moduleNodes.item(0);
            module.setAggregator(true);
            NodeList children = modulesEl.getChildNodes();
            for (int i = 0; i < children.getLength(); i++) {
                Node child = children.item(i);
                if (child.getNodeType() == Node.ELEMENT_NODE && "module".equals(child.getNodeName())) {
                    String modulePath = child.getTextContent().trim();
                    Path moduleDir = canonical.getParent().resolve(modulePath).normalize();
                    Path modulePom = moduleDir.resolve("pom.xml");
                    log.info("[MODULE_SCAN] Found sub-module: {} -> {}", modulePath, modulePom);
                    if (Files.exists(modulePom)) {
                        scanRecursive(modulePom, basedir, modules, visited);
                    } else {
                        log.warn("[MODULE_SCAN] Declared module '{}' not found at {}", modulePath, modulePom);
                    }
                }
            }
        }
    }

    private MavenModule parseModule(Document doc, Path pomFile, Path basedir) {
        MavenModule module = new MavenModule();
        Element root = doc.getDocumentElement();

        // <parent> — 继承 groupId/version
        String parentGroupId = null;
        String parentVersion = null;
        NodeList parentNodes = root.getElementsByTagName("parent");
        if (parentNodes.getLength() > 0) {
            Element parent = (Element) parentNodes.item(0);
            parentGroupId = getChildText(parent, "groupId");
            parentVersion = getChildText(parent, "version");
            // parentArtifactId 暂时没用
        }

        module.setGroupId(firstNonNull(getChildText(root, "groupId"), parentGroupId));
        module.setArtifactId(getChildText(root, "artifactId"));
        module.setVersion(firstNonNull(getChildText(root, "version"), parentVersion));
        module.setPackaging(firstNonNull(getChildText(root, "packaging"), "jar"));
        module.setPomFile(pomFile.toAbsolutePath().normalize());
        module.setBaseDir(pomFile.getParent().toAbsolutePath().normalize());
        module.setModulePath(toModulePath(basedir, module.getBaseDir()));

        // source roots
        List<Path> sourceRoots = new ArrayList<>();
        Path srcMainJava = module.getBaseDir().resolve("src/main/java");
        if (Files.isDirectory(srcMainJava)) {
            sourceRoots.add(srcMainJava);
        }
        module.setSourceRoots(sourceRoots);

        // 初始分类：pom 无源码 → AGGREGATOR，其余扫描结束后由 ModuleClassifier 处理
        if ("pom".equalsIgnoreCase(module.getPackaging()) && sourceRoots.isEmpty()) {
            module.setModuleType(ModuleType.AGGREGATOR);
        }

        return module;
    }

    private Document parseXml(Path file) {
        try {
            DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
            factory.setFeature("http://apache.org/xml/features/nonvalidating/load-external-dtd", false);
            factory.setFeature("http://xml.org/sax/features/external-general-entities", false);
            factory.setFeature("http://xml.org/sax/features/external-parameter-entities", false);
            DocumentBuilder builder = factory.newDocumentBuilder();
            return builder.parse(file.toFile());
        } catch (Exception e) {
            log.warn("Failed to parse POM {}: {}", file, e.getMessage());
            return null;
        }
    }

    private String getChildText(Element parent, String tagName) {
        NodeList children = parent.getChildNodes();
        for (int i = 0; i < children.getLength(); i++) {
            Node child = children.item(i);
            if (child.getNodeType() == Node.ELEMENT_NODE && tagName.equals(child.getNodeName())) {
                return child.getTextContent().trim();
            }
        }
        return null;
    }

    private String toModulePath(Path basedir, Path moduleDir) {
        if (basedir == null || moduleDir == null) {
            return null;
        }
        String relative = basedir.toAbsolutePath().normalize()
                .relativize(moduleDir.toAbsolutePath().normalize())
                .toString()
                .replace('\\', '/');
        return relative.isEmpty() ? "." : relative;
    }

    private String firstNonNull(String... values) {
        for (String v : values) {
            if (v != null && !v.isEmpty()) return v;
        }
        return null;
    }
}
