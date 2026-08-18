package com.argus.analyzer.domain.model;

import java.util.List;

/**
 * 调用图方法键的统一编解码工具（收敛 {@code className + "#" + methodName} 的四处散落实现）。
 *
 * <p>名字键 {@code className#methodName} 是稳定身份，供「仅有方法名」的消费方（端点入口、
 * scope 回退边、外部叶子）反查图；同一类内重载方法用签名键 {@code className#methodName(参数类型)}
 * 区分，避免同名方法静默互相覆盖。名字键始终指向首个重载，签名键仅用于区分后续重载。</p>
 */
public final class MethodKey {

    private MethodKey() {
    }

    /** 名字键：{@code className#methodName}。 */
    public static String nameKey(String className, String methodName) {
        return className + "#" + methodName;
    }

    /** 签名键：{@code className#methodName(paramType1,paramType2)}。 */
    public static String signatureKey(String className, String methodName, List<String> paramTypes) {
        return nameKey(className, methodName) + "(" + String.join(",", paramTypes) + ")";
    }

    /** 从键提取类名；无 {@code #} 时返回空串。 */
    public static String classNameOf(String key) {
        int hash = key.indexOf('#');
        return hash > 0 ? key.substring(0, hash) : "";
    }

    /** 从键提取方法名（剥离 {@code (…)} 参数后缀）。 */
    public static String methodNameOf(String key) {
        int hash = key.indexOf('#');
        String method = hash >= 0 ? key.substring(hash + 1) : key;
        int paren = method.indexOf('(');
        return paren > 0 ? method.substring(0, paren) : method;
    }
}
