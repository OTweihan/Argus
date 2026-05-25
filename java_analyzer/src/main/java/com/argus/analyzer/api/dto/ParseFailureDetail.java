package com.argus.analyzer.api.dto;

import java.util.List;

public class ParseFailureDetail {

    private String file;
    private List<String> problems;

    public ParseFailureDetail() {}

    public ParseFailureDetail(String file, List<String> problems) {
        this.file = file;
        this.problems = problems;
    }

    public String getFile() { return file; }
    public void setFile(String file) { this.file = file; }

    public List<String> getProblems() { return problems; }
    public void setProblems(List<String> problems) { this.problems = problems; }
}
