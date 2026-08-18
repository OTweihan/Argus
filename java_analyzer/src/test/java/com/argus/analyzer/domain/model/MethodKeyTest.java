package com.argus.analyzer.domain.model;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class MethodKeyTest {

    @Test
    void nameKeyConcatenatesClassNameAndMethod() {
        assertThat(MethodKey.nameKey("com.example.UserController", "getUser"))
                .isEqualTo("com.example.UserController#getUser");
    }

    @Test
    void signatureKeyAppendsParamTypeList() {
        assertThat(MethodKey.signatureKey("com.example.User", "foo", List.of("int", "String")))
                .isEqualTo("com.example.User#foo(int,String)");
    }

    @Test
    void classNameOfSplitsOnHash() {
        assertThat(MethodKey.classNameOf("com.example.User#foo(int)"))
                .isEqualTo("com.example.User");
        assertThat(MethodKey.classNameOf("com.example.User#foo")).isEqualTo("com.example.User");
    }

    @Test
    void classNameOfReturnsEmptyForRawName() {
        assertThat(MethodKey.classNameOf("foo")).isEmpty();
    }

    @Test
    void methodNameOfStripsParamSuffix() {
        assertThat(MethodKey.methodNameOf("com.example.User#foo(int,String)"))
                .isEqualTo("foo");
        assertThat(MethodKey.methodNameOf("com.example.User#foo")).isEqualTo("foo");
        assertThat(MethodKey.methodNameOf("rawCall")).isEqualTo("rawCall");
    }
}
